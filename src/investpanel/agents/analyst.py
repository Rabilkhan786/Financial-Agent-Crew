"""Analyst — the cross-check that is the entire point of this project.

The analyst does NOT just merge the three specialists' reports. It compares
specific claims across them — a number from Financial against a narrative from
News or a risk signal from Risk — and looks for genuine tension. The comparison
is built as explicit detectors over structured fields (below), not as a vague
"does this feel consistent?" prompt, so it is mechanical, testable, and defensible
in an interview. When it finds a contradiction, it aims one specific follow-up
question at exactly one specialist. Only if that still leaves things unresolved
(and within the round limit) does it write the report.

An optional LLM pass can add subtler contradictions on top of the deterministic
detectors, but the detectors are the backbone and are what the tests pin down.
"""

import json

from investpanel import config
from investpanel.agents.base import BaseAgent
from investpanel.models.contradiction import Contradiction, Tension
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding
from investpanel.models.observation import Observation
from investpanel.models.report import Report
from investpanel.utils.logging import get_logger
from investpanel.utils.numeric_guard import extract_numbers, verify_summary
from investpanel.utils.observations import collect_observations

logger = get_logger(__name__)


def _high_volatility(risk: list[RiskFinding]) -> bool:
    return any(
        f.metric == "annualized_volatility" and f.value > config.HIGH_VOLATILITY_THRESHOLD
        for f in risk
    )


def _negative_news(news: list[NewsFinding]) -> list[NewsFinding]:
    """High-relevance news that flags a management or risk concern."""
    return [n for n in news if n.relevance == "high" and n.checklist_question in ("management", "risk")]


def detect_contradictions(
    financial: list[FinancialFinding],
    news: list[NewsFinding],
    risk: list[RiskFinding],
    peer_comparison: dict[str, dict[str, float]] | None = None,
    target_ticker: str | None = None,
) -> list[Contradiction]:
    """The deterministic core cross-check. Pure function, fully unit-testable.

    Each detector compares a concrete signal from one specialist against a concrete
    signal from another and, on a mismatch, returns a Contradiction with a specific
    follow-up aimed at one specialist.
    """
    contradictions: list[Contradiction] = []
    by_metric = {f.metric: f for f in financial}
    all_financials_healthy = bool(financial) and all(f.healthy for f in financial)
    any_financial_unhealthy = any(not f.healthy for f in financial)
    high_vol = _high_volatility(risk)
    negative = _negative_news(news)

    # Detector 1: the spec's headline example — healthy fundamentals sitting next to
    # an unexplained volatility spike that no news accounts for. Ask News to explain it.
    if high_vol and all_financials_healthy and not negative:
        contradictions.append(Contradiction(
            between=("risk", "news"),
            description=(
                "Share-price volatility is elevated, yet every financial metric looks "
                "healthy and no recent high-relevance news explains the risk."
            ),
            follow_up_target="news",
            follow_up_question=(
                "Find the specific recent events or disclosures that explain the elevated "
                "share-price volatility, despite healthy reported fundamentals."
            ),
        ))

    # Detector 2: numbers say all-good, but the news carries a serious management/risk
    # story. The numbers may be lagging the story — ask Financial to look closer.
    if all_financials_healthy and negative:
        item = negative[0]
        contradictions.append(Contradiction(
            between=("financial", "news"),
            description=(
                f"Financials look healthy, but recent news raises a {item.checklist_question} "
                f"concern: \"{item.headline}\"."
            ),
            follow_up_target="financial",
            follow_up_question=(
                "Re-examine the latest financials (cash flow, margins, one-off items) for any "
                f"early sign of the issue raised in the news: \"{item.headline}\"."
            ),
        ))

    # Detector 3: valuation looks cheap while some fundamentals are weak AND volatility
    # is elevated — the classic value-trap pattern. Ask Risk to quantify the downside.
    valuation_cheap = (
        (by_metric.get("valuation_vs_growth") and by_metric["valuation_vs_growth"].healthy)
        or (by_metric.get("pe_ratio") and by_metric["pe_ratio"].healthy)
    )
    if valuation_cheap and high_vol and any_financial_unhealthy:
        contradictions.append(Contradiction(
            between=("financial", "risk"),
            description=(
                "Valuation looks cheap, but some fundamentals are weak and volatility is "
                "elevated — a possible value trap rather than a bargain."
            ),
            follow_up_target="risk",
            follow_up_question=(
                "Quantify the downside: how large is the drawdown/volatility, and does it point "
                "to a value trap rather than an undervalued but stable business?"
            ),
        ))

    # Detector 4: the market pays a premium (expensive P/E) while the fundamentals
    # are actually shrinking (revenue or profit falling). The price implies growth
    # the numbers don't show — a direct valuation-vs-fundamentals contradiction.
    pe = by_metric.get("pe_ratio")
    profit = by_metric.get("profit_growth")
    revenue = by_metric.get("revenue_growth")
    expensive = pe is not None and not pe.healthy
    shrinking = (profit is not None and profit.value < 0) or (revenue is not None and revenue.value < 0)
    if expensive and shrinking:
        contradictions.append(Contradiction(
            between=("financial", "news"),
            description=(
                f"Valuation is rich (P/E {pe.value:.0f}) but the fundamentals are shrinking "
                "(revenue and/or profit declining) — the price implies growth the numbers don't show."
            ),
            follow_up_target="news",
            follow_up_question=(
                "What specific recent developments (new products, guidance, strategic shifts) are "
                "cited to justify the premium valuation despite declining revenue/profit?"
            ),
        ))

    # Detector 5: earnings quality — reported profit is growing, but operating cash
    # flow doesn't back it up. This is a number-vs-number check a single LLM won't do.
    ocf = by_metric.get("operating_cash_flow")
    if profit is not None and profit.value > 0 and ocf is not None and not ocf.healthy:
        contradictions.append(Contradiction(
            between=("financial", "news"),
            description=(
                "Reported profit is growing, but operating cash flow doesn't back it up — "
                "a possible earnings-quality red flag."
            ),
            follow_up_target="news",
            follow_up_question=(
                "Are there recent disclosures (one-off gains, accounting changes, receivables "
                "build-up) explaining why cash flow lags reported profit?"
            ),
        ))

    # Detector 6: peer-relative — the company is growing far slower than its actual
    # competitors. Uses the sourced peer table (something a single LLM can't reliably build).
    if peer_comparison and target_ticker:
        target = target_ticker.upper()
        for metric_name in ("revenue_growth", "profit_growth"):
            values = peer_comparison.get(metric_name, {})
            target_val = values.get(target)
            peers = [v for t, v in values.items() if t != target]
            if target_val is None or not peers:
                continue
            peer_avg = sum(peers) / len(peers)
            # Materially behind: below half the (positive) peer average and a >10pt gap.
            if peer_avg > 0 and target_val < peer_avg * 0.5 and (peer_avg - target_val) > 10:
                contradictions.append(Contradiction(
                    between=("financial", "news"),
                    description=(
                        f"{metric_name.replace('_', ' ')} is {target_val:.0f}% versus a peer "
                        f"average of {peer_avg:.0f}% — the company is growing well behind its competitors."
                    ),
                    follow_up_target="news",
                    follow_up_question=(
                        f"What company-specific issues explain {target}'s "
                        f"{metric_name.replace('_', ' ')} lagging its peers so badly?"
                    ),
                ))
                break  # one peer-lag flag is enough

    return contradictions


def detect_potential_tensions(
    financial: list[FinancialFinding],
    news: list[NewsFinding],
    risk: list[RiskFinding],
) -> list[Tension]:
    """Softer signals worth a reader's attention that are NOT automatically a
    genuine contradiction — kept deliberately separate from detect_contradictions
    so these never drive the follow-up loop. Pure function, unit-testable.

    These exist so the report can be honest: "revenue up, profit down" deserves a
    flag, but calling it a "contradiction" would overstate what the numbers show
    (many healthy companies see this from rising costs or one-off items).
    """
    tensions: list[Tension] = []
    by_metric = {f.metric: f for f in financial}

    revenue = by_metric.get("revenue_growth")
    profit = by_metric.get("profit_growth")
    if revenue is not None and profit is not None and revenue.healthy and not profit.healthy:
        tensions.append(Tension(
            between=("financial", "financial"),
            description=(
                f"Revenue growth is {revenue.value:.1f}% while profit growth is "
                f"{profit.value:.1f}% — revenue is increasing while profit is declining."
            ),
            reason=(
                "This is not automatically a contradiction, but it warrants investigation "
                "into margins, costs, or other factors eating into profitability."
            ),
        ))

    pe = by_metric.get("pe_ratio")
    if pe is not None and not pe.healthy and profit is not None and profit.healthy:
        tensions.append(Tension(
            between=("financial", "financial"),
            description=(
                f"Valuation is rich (P/E {pe.value:.0f}) while profit is genuinely growing "
                f"({profit.value:.1f}%) — the market may already be pricing in that growth."
            ),
            reason=(
                "Not a contradiction — growth can justify a premium — but worth monitoring "
                "if growth decelerates, since the valuation leaves little room for a miss."
            ),
        ))

    return tensions


def explain_consistency(financial: list[FinancialFinding], news: list[NewsFinding]) -> str | None:
    """When profit growth is a concern AND a risk/management news item plausibly
    explains it, that pairing is CONSISTENT, not contradictory — the numbers and
    the story agree. Returns an explanation when that pattern holds, else None."""
    profit = next((f for f in financial if f.metric == "profit_growth"), None)
    if profit is None or profit.healthy:
        return None
    explaining_news = [n for n in news if n.relevance == "high" and n.checklist_question in ("management", "risk")]
    if not explaining_news:
        return None
    item = explaining_news[0]
    return (
        f'Financial finding: profit growth {profit.value:.1f}%. '
        f'News finding: "{item.headline}". '
        "Analyst assessment: consistent — the news provides a plausible explanation "
        "for the weaker profit growth rather than contradicting it."
    )


LLM_CROSSCHECK_PROMPT = """You are checking whether an investment panel's findings agree.
Below are the numeric findings, the news findings, and the risk findings as JSON.

Find any GENUINE contradiction where a NUMBER disagrees with a NARRATIVE or a RISK signal
(e.g. "margins improved" vs "restructuring announced last month"). Do not invent tension
that isn't there; return an empty list if the findings are consistent.

Return ONLY JSON: {{"contradictions": [
  {{"between": ["financial"|"news"|"risk", "financial"|"news"|"risk"],
    "description": "...",
    "follow_up_target": "financial"|"news"|"risk",
    "follow_up_question": "a specific question"}}
]}}

FINANCIAL: {financial}
NEWS: {news}
RISK: {risk}
"""


class AnalystAgent(BaseAgent):
    """Runs the cross-check, drives the follow-up, and writes the final report."""

    name = "analyst"

    def cross_check(
        self,
        financial: list[FinancialFinding],
        news: list[NewsFinding],
        risk: list[RiskFinding],
        peer_comparison: dict[str, dict[str, float]] | None = None,
        target_ticker: str | None = None,
    ) -> list[Contradiction]:
        """Return contradictions from the deterministic detectors, plus (if an LLM
        is available) any additional ones the model spots. The detectors always run."""
        contradictions = detect_contradictions(
            financial, news, risk, peer_comparison, target_ticker
        )
        if self.llm is not None:
            contradictions.extend(self._llm_cross_check(financial, news, risk))
        self.trace({
            "num_contradictions": len(contradictions),
            "contradictions": [c.model_dump(mode="json") for c in contradictions],
        })
        return contradictions

    def _llm_cross_check(self, financial, news, risk) -> list[Contradiction]:
        prompt = LLM_CROSSCHECK_PROMPT.format(
            financial=json.dumps([f.model_dump(mode="json") for f in financial]),
            news=json.dumps([n.model_dump(mode="json") for n in news]),
            risk=json.dumps([r.model_dump(mode="json") for r in risk]),
        )
        try:
            data = self.invoke_json(prompt)
            found = []
            for raw in data.get("contradictions", []):
                found.append(Contradiction(
                    between=tuple(raw["between"]),
                    description=raw["description"],
                    follow_up_target=raw["follow_up_target"],
                    follow_up_question=raw["follow_up_question"],
                ))
            return found
        except Exception:  # noqa: BLE001 - the deterministic detectors are the backbone; an LLM hiccup must not break the run
            return []

    def write_report(
        self,
        company: str,
        company_description: str,
        financial: list[FinancialFinding],
        news: list[NewsFinding],
        risk: list[RiskFinding],
        contradictions: list[Contradiction],
        contradictions_resolved: int,
        peer_comparison: dict[str, dict[str, float]],
        followup_targets_executed: list[str] | None = None,
        ticker: str | None = None,
        question: str | None = None,
        interpreted_question: str | None = None,
        price_history: list[float] | None = None,
        query_intent: str | None = None,
        routing_reason: str | None = None,
        skipped_agents: list[str] | None = None,
        tensions: list[Tension] | None = None,
        additional_findings: list[Observation] | None = None,
    ) -> Report:
        """Assemble the final Report. The disclaimer is added by the model itself."""
        report = Report(
            company=company,
            ticker=ticker,
            question=question,
            interpreted_question=interpreted_question,
            query_intent=query_intent,
            routing_reason=routing_reason,
            skipped_agents=skipped_agents or [],
            company_description=company_description or "Description unavailable.",
            summary=self._summary(company, financial, news, risk, contradictions, tensions or []),
            checklist_answers=build_checklist_answers(financial, news, risk),
            peer_comparison=peer_comparison,
            financial_findings=financial,
            news_findings=news,
            risk_findings=risk,
            price_history=price_history or [],
            contradictions_found=contradictions,
            contradictions_resolved=contradictions_resolved,
            # Use what the Critic raised. Only fall back to computing them here if
            # no critic ran, so a focused test or older caller still gets tensions.
            potential_tensions=(
                tensions if tensions is not None else detect_potential_tensions(financial, news, risk)
            ),
            # Same pattern: use what the Critic surfaced, but still work standalone.
            additional_findings=(
                additional_findings if additional_findings is not None
                else collect_observations(financial, news, risk)
            ),
            followup_targets_executed=followup_targets_executed or [],
        )
        self.trace({"company": company, "report_summary": report.summary})
        return report

    def _summary(self, company, financial, news, risk, contradictions, tensions=None) -> str:
        """The report's short "Key Takeaway".

        Asks the LLM to synthesize the validated findings. If no LLM is reachable
        (no API key, rate limit, provider error) we fall back to a plain template
        built only from counts — a run must never fail just because the prose
        summary couldn't be written.
        """
        fallback = (
            f"{company}: {sum(1 for f in financial if f.healthy)}/{len(financial)} financial "
            f"metrics healthy, {len(news)} news items reviewed, "
            f"{len(contradictions)} contradiction(s) found."
        )
        # The Critic's output is passed in as something the takeaway must ADDRESS.
        # Left out, an LLM naturally writes a tidy story and the conflict disappears —
        # which is exactly the failure the Critic step exists to prevent.
        critic_note = ""
        if contradictions or tensions:
            critic_note = (
                "A Critic reviewed these findings and raised the CONTRADICTIONS and "
                "TENSIONS below. Your takeaway MUST acknowledge them rather than "
                "smoothing them over or ignoring them.\n"
            )
        prompt = (
            f"Write a 2-4 sentence 'Key Takeaway' for {company}, synthesizing ONLY the "
            f"validated findings below. Do not state any number that is not already present "
            f"in the findings. Do not give a buy/sell/hold recommendation.\n"
            f"{critic_note}"
            f"FINANCIAL: {json.dumps([f.model_dump(mode='json') for f in financial])}\n"
            f"NEWS: {json.dumps([n.model_dump(mode='json') for n in news])}\n"
            f"RISK: {json.dumps([r.model_dump(mode='json') for r in risk])}\n"
            f"CONTRADICTIONS: {json.dumps([c.model_dump(mode='json') for c in contradictions])}\n"
            f"TENSIONS: {json.dumps([t.model_dump(mode='json') for t in (tensions or [])])}\n"
        )
        try:
            reply = self._ensure_llm().invoke(prompt)
        except Exception:  # noqa: BLE001 - no key / rate limit / provider error: use the template
            return fallback
        text = getattr(reply, "content", str(reply)).strip()
        # Models often echo the label back; the report already prints it as a heading.
        for prefix in ("Key Takeaway:", "**Key Takeaway:**", "Key takeaway:"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        if not text:
            return fallback

        # CHANGE 2's guarantee, enforced in code rather than trusted to the prompt:
        # every figure in the prose must trace back to a number Python computed. If
        # the model invented one, we drop the prose entirely rather than publish a
        # fabricated financial figure.
        allowed = _allowed_numbers(financial, risk)
        clean, offenders = verify_summary(text, allowed)
        if not clean:
            logger.warning(
                "Discarding generated summary: numbers not in the findings: %s", offenders
            )
            self.trace({"rejected_summary": text, "unsupported_numbers": offenders})
            return fallback
        return text


def _allowed_numbers(financial, risk) -> list[float]:
    """Every number the summary may legitimately quote.

    Not just the metric values: the findings' own sentences carry real numbers too
    ("100-day close series", "versus a 40% threshold"). Those are computed facts the
    model is entitled to repeat, so leaving them out makes the guard reject good
    summaries — which is how a safety check quietly becomes a quality problem.
    """
    values = [f.value for f in financial] + [r.value for r in risk]
    for finding in [*financial, *risk]:
        text = " ".join(
            str(getattr(finding, field, "") or "")
            for field in ("interpretation", "computed_from", "period", "source")
        )
        values.extend(extract_numbers(text))
    return values


# Which financial metric answers which checklist question.
_METRIC_TO_Q = {
    "q2": ["revenue_growth"],
    "q3": ["profit_growth"],
    "q4": ["operating_cash_flow"],
    "q5": ["debt_to_equity", "interest_coverage"],
    "q6": ["roce", "roe"],
    "q10": ["pe_ratio", "pb_ratio", "valuation_vs_growth"],
}


def build_checklist_answers(
    financial: list[FinancialFinding],
    news: list[NewsFinding],
    risk: list[RiskFinding],
) -> dict[str, str]:
    """Fill in checklist answers q2-q10, marking anything unsupported as insufficient.

    The numeric questions read straight from the financial findings; the judgment
    questions (moat/management/risk) are answered only if a sourced news finding
    supports them, otherwise "insufficient evidence" — which is exactly what the
    completeness metric in docs/evaluation.md measures.
    """
    by_metric = {f.metric: f for f in financial}
    answers: dict[str, str] = {}

    for q_key, metrics in _METRIC_TO_Q.items():
        parts = []
        for metric in metrics:
            finding = by_metric.get(metric)
            if finding:
                verdict = "healthy" if finding.healthy else "a concern"
                parts.append(f"{metric}={finding.value}{finding.unit and ' ' + finding.unit} ({verdict})")
        answers[q_key] = "; ".join(parts) if parts else "insufficient evidence"

    # Q7 moat, Q8 management: answered from tagged, sourced news only.
    answers["q7"] = _news_answer(news, "moat")
    answers["q8"] = _news_answer(news, "management")

    # Q9 risk: combine risk findings with any risk-tagged news.
    risk_bits = [r.interpretation for r in risk]
    risk_news = [n.headline for n in news if n.checklist_question == "risk"]
    if risk_bits or risk_news:
        answers["q9"] = "; ".join(risk_bits + risk_news)
    else:
        answers["q9"] = "insufficient evidence"

    return answers


def _news_answer(news: list[NewsFinding], tag: str) -> str:
    """Answer a judgment question from news items tagged for it, or say we can't."""
    tagged = [n for n in news if n.checklist_question == tag]
    if not tagged:
        return "insufficient evidence"
    return "; ".join(f"{n.headline} ({n.relevance})" for n in tagged)
