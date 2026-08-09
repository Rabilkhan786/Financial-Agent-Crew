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
from investpanel.models.contradiction import Contradiction
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding
from investpanel.models.report import Report


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

    return contradictions


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
    ) -> list[Contradiction]:
        """Return contradictions from the deterministic detectors, plus (if an LLM
        is available) any additional ones the model spots. The detectors always run."""
        contradictions = detect_contradictions(financial, news, risk)
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
    ) -> Report:
        """Assemble the final Report. The disclaimer is added by the model itself."""
        report = Report(
            company=company,
            company_description=company_description or "Description unavailable.",
            summary=self._summary(company, financial, news, risk, contradictions),
            checklist_answers=build_checklist_answers(financial, news, risk),
            peer_comparison=peer_comparison,
            financial_findings=financial,
            news_findings=news,
            risk_findings=risk,
            contradictions_found=contradictions,
            contradictions_resolved=contradictions_resolved,
        )
        self.trace({"company": company, "report_summary": report.summary})
        return report

    def _summary(self, company, financial, news, risk, contradictions) -> str:
        """A short overall summary. Uses the LLM if available, else a plain template."""
        if self.llm is None:
            healthy = sum(1 for f in financial if f.healthy)
            return (
                f"{company}: {healthy}/{len(financial)} financial metrics healthy, "
                f"{len(news)} news items reviewed, {len(contradictions)} contradiction(s) found."
            )
        prompt = (
            f"Write 3-4 sentences of balanced summary for {company} based ONLY on these "
            f"findings. Do not give a buy/sell recommendation.\n"
            f"FINANCIAL: {json.dumps([f.model_dump(mode='json') for f in financial])}\n"
            f"NEWS: {json.dumps([n.model_dump(mode='json') for n in news])}\n"
            f"RISK: {json.dumps([r.model_dump(mode='json') for r in risk])}\n"
            f"CONTRADICTIONS: {json.dumps([c.model_dump(mode='json') for c in contradictions])}\n"
        )
        reply = self._ensure_llm().invoke(prompt)
        return getattr(reply, "content", str(reply)).strip()


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
