"""Deterministic interpretation of a Report — no LLM, no new facts.

Every function here reads ONLY fields already present on a Report (or the
findings/config it's built from) and derives a presentation-ready label,
classification, or table from them. Nothing here calls an API or an LLM, and
nothing here invents a number that isn't already on a finding — that's the
"facts vs interpretation" rule from the spec: this module produces the
*interpretation* layer, but every interpretation traces back to a concrete,
sourced value a reader can check against the "All findings with sources"
section. Kept separate from agents/ (which does the LLM reasoning and evidence
gathering) and from app.py (which only renders what this module hands it).
"""

from investpanel import config
from investpanel.models.contradiction import Contradiction
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding
from investpanel.models.report import Report
from investpanel.utils.report_format import (
    format_drawdown,
    format_metric_label,
    format_metric_value,
    format_volatility,
)

# --- Executive-summary category labels ---------------------------------------
# Deterministic, not LLM-chosen: every label below is decided by a fixed rule
# over the `healthy` flags the specialists already computed. "Insufficient
# evidence" always wins when there's nothing to classify — we never guess.

POSITIVE, NEGATIVE, MIXED, INSUFFICIENT = "Positive", "Negative", "Mixed", "Insufficient evidence"


def _classify_healthy_flags(flags: list[bool]) -> str:
    """The shared rule behind every category label: all-healthy -> Positive,
    all-unhealthy -> Negative, a mix -> Mixed, nothing to look at -> Insufficient."""
    if not flags:
        return INSUFFICIENT
    if all(flags):
        return POSITIVE
    if not any(flags):
        return NEGATIVE
    return MIXED


def _flags_for(financial: list[FinancialFinding], metrics: set[str]) -> list[bool]:
    return [f.healthy for f in financial if f.metric in metrics]


def classify_growth(financial: list[FinancialFinding]) -> str:
    return _classify_healthy_flags(_flags_for(financial, {"revenue_growth", "profit_growth"}))


def classify_profitability(financial: list[FinancialFinding]) -> str:
    return _classify_healthy_flags(
        _flags_for(financial, {"profit_growth", "operating_cash_flow", "roe", "roce"})
    )


def classify_valuation(financial: list[FinancialFinding]) -> str:
    """Uses "Reasonable" / "Rich" / "Insufficient evidence" — valuation isn't a
    growth/profit direction, so Positive/Negative would be misleading wording."""
    flags = _flags_for(financial, {"pe_ratio", "pb_ratio", "valuation_vs_growth"})
    if not flags:
        return INSUFFICIENT
    if all(flags):
        return "Reasonable"
    if not any(flags):
        return "Rich"
    return MIXED


def classify_fundamentals(financial: list[FinancialFinding]) -> str:
    """Overall balance-sheet health across every computed financial metric."""
    return _classify_healthy_flags([f.healthy for f in financial])


def classify_risk(risk: list[RiskFinding]) -> str:
    """"Moderate" / "Elevated" from the same threshold the Risk agent itself
    uses (config.HIGH_VOLATILITY_THRESHOLD) — never a fresh, invented cutoff."""
    vol = next((f.value for f in risk if f.metric == "annualized_volatility"), None)
    drawdown = next((f.value for f in risk if f.metric == "max_drawdown"), None)
    if vol is None and drawdown is None:
        return INSUFFICIENT
    elevated = (vol is not None and vol > config.HIGH_VOLATILITY_THRESHOLD) or (
        drawdown is not None and drawdown > config.CONCERNING_DRAWDOWN_THRESHOLD
    )
    return "Elevated" if elevated else "Moderate"


def classify_news(news: list[NewsFinding]) -> str:
    """Based only on the tags the News agent already assigned (relevance +
    checklist_question) — never a sentiment guess over the article text."""
    if not news:
        return INSUFFICIENT
    concerns = [n for n in news if n.relevance == "high" and n.checklist_question in ("management", "risk")]
    positives = [n for n in news if n.relevance == "high" and n.checklist_question == "moat"]
    if concerns and positives:
        return MIXED
    if concerns:
        return "Concerns flagged"
    return "No major concerns flagged"


def build_executive_summary(report: Report) -> dict[str, str]:
    """The category ratings shown at the top of the report — every value here
    is one of the classify_* functions above, so it's fully reproducible."""
    return {
        "Fundamentals": classify_fundamentals(report.financial_findings),
        "Growth": classify_growth(report.financial_findings),
        "Profitability": classify_profitability(report.financial_findings),
        "Valuation": classify_valuation(report.financial_findings),
        "Risk": classify_risk(report.risk_findings),
        "News": classify_news(report.news_findings),
    }


# --- Evidence quality ----------------------------------------------------------

def _financial_quality(financial: list[FinancialFinding]) -> str:
    n = len(financial)
    if n >= config.EVIDENCE_HIGH_FINANCIAL_METRICS:
        return "High"
    if n >= config.EVIDENCE_MEDIUM_FINANCIAL_METRICS:
        return "Medium"
    if n > 0:
        return "Low"
    return "Insufficient"


def _news_quality(news: list[NewsFinding]) -> str:
    n = len(news)
    if n >= config.EVIDENCE_HIGH_NEWS_ARTICLES:
        return "High"
    if n >= config.EVIDENCE_MEDIUM_NEWS_ARTICLES:
        return "Medium"
    return "Insufficient"


def _risk_quality(risk: list[RiskFinding]) -> str:
    if not risk:
        return "Insufficient"
    # RiskFinding.computed_from looks like "252-day close series, AlphaVantage".
    for finding in risk:
        digits = "".join(ch for ch in finding.computed_from.split("-day")[0] if ch.isdigit())
        if digits and int(digits) >= config.EVIDENCE_HIGH_PRICE_DAYS:
            return "High"
    return "Medium"


def _peer_quality(peer_comparison: dict[str, dict[str, float]], target_ticker: str | None) -> str:
    if not peer_comparison:
        return "Insufficient"
    target = (target_ticker or "").upper()
    max_peers = max((len(v) - (1 if target in v else 0) for v in peer_comparison.values()), default=0)
    if max_peers >= config.EVIDENCE_HIGH_PEER_COUNT:
        return "High"
    if max_peers >= 1:
        return "Medium"
    return "Low"


_QUALITY_RANK = {"Insufficient": 0, "Low": 1, "Medium": 2, "High": 3}


def evidence_quality(report: Report, target_ticker: str | None = None) -> dict[str, str]:
    """Per-source and overall evidence quality — deterministic rules, not an LLM
    opinion, so the same Report always gets the same rating.

    Overall = the weakest of the three REQUIRED sources (financial/news/risk).
    Peer data is supplementary to the checklist, so it's reported but doesn't
    drag the overall rating down on its own.
    """
    per_source = {
        "Financial": _financial_quality(report.financial_findings),
        "News": _news_quality(report.news_findings),
        "Risk": _risk_quality(report.risk_findings),
        "Peer comparison": _peer_quality(report.peer_comparison, target_ticker),
    }
    required = [per_source["Financial"], per_source["News"], per_source["Risk"]]
    overall = min(required, key=lambda label: _QUALITY_RANK[label])
    per_source["Overall"] = overall
    return per_source


# --- Data freshness ------------------------------------------------------------

def data_freshness(report: Report) -> dict[str, str]:
    """What time window each piece of evidence actually covers — pulled from
    the findings themselves, never assumed. "Period unavailable" is honest when
    a source doesn't give us anything to report."""
    periods = sorted({f.period for f in report.financial_findings if f.period})
    financial_period = ", ".join(periods) if periods else "Period unavailable"

    dates = sorted(n.published_date for n in report.news_findings if n.published_date)
    if not dates:
        news_window = "Period unavailable"
    elif dates[0] == dates[-1]:
        news_window = dates[0].isoformat()
    else:
        news_window = f"{dates[0].isoformat()} to {dates[-1].isoformat()}"

    price_window = "Period unavailable"
    for finding in report.risk_findings:
        digits = "".join(ch for ch in finding.computed_from.split("-day")[0] if ch.isdigit())
        if digits:
            price_window = f"{digits} trading days of price history"
            break

    return {
        "Research date": report.generated_at,
        "Financial data period": financial_period,
        "News coverage window": news_window,
        "Price/risk analysis window": price_window,
    }


# --- Peer comparison table ------------------------------------------------------

def build_peer_table(peer_comparison: dict[str, dict[str, float]]) -> list[dict[str, str]]:
    """Turn {metric: {ticker: value}} into a list of display rows, one per
    metric, with every value pre-formatted. Only metrics that actually have
    data appear — no fabricated blank cells."""
    rows = []
    for metric, values in peer_comparison.items():
        if not values:
            continue
        row = {"Metric": _metric_label(metric)}
        for ticker, value in values.items():
            row[ticker] = format_metric_value(metric, value)
        rows.append(row)
    return rows


def _metric_label(metric: str) -> str:
    return format_metric_label(metric)


# Metrics worth charting against peers: comparable across companies and on a scale
# where a bar chart is meaningful (cash flow, for instance, just tracks company size).
CHARTABLE_PEER_METRICS = ["revenue_growth", "profit_growth", "roe", "pe_ratio"]


def peer_chart_data(peer_comparison: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """{metric label: {ticker: raw value}} for the peer bar charts.

    Only includes metrics that have at least two companies — a one-bar chart
    comparing a company to nothing would be misleading.
    """
    charts = {}
    for metric in CHARTABLE_PEER_METRICS:
        values = peer_comparison.get(metric, {})
        if len(values) >= 2:
            charts[_metric_label(metric)] = values
    return charts


# --- Risk section ---------------------------------------------------------------

def build_risk_summary(risk: list[RiskFinding]) -> list[dict[str, str]]:
    """One display row per risk finding, formatted for a reader."""
    rows = []
    for f in risk:
        if f.metric == "annualized_volatility":
            value = format_volatility(f.value)
        elif f.metric == "max_drawdown":
            value = format_drawdown(f.value)
        else:
            value = format_metric_value(f.metric, f.value)
        rows.append({
            "metric": _metric_label(f.metric),
            "value": value,
            "interpretation": f.interpretation,
            "computed_from": f.computed_from,
        })
    return rows


# --- Facts vs interpretation grouping for the checklist -------------------------

_METRIC_QUESTIONS: dict[str, tuple[str, str]] = {
    "revenue_growth": ("Is revenue growing?", "Indicates whether the top line is expanding or contracting."),
    "profit_growth": ("Are profits growing?", "Shows whether growth is reaching the bottom line, not just revenue."),
    "operating_cash_flow": (
        "Does the company generate cash?",
        "Positive operating cash flow funds the business without relying on new debt or shares.",
    ),
    "debt_to_equity": ("Is debt manageable?", "High leverage increases financial risk if earnings dip."),
    "interest_coverage": ("Can it service its interest payments?", "Low coverage signals debt could become a burden."),
    "roce": ("Is capital being used efficiently (ROCE)?", "Measures how well the company turns capital into returns."),
    "roe": ("Is capital being used efficiently (ROE)?", "Measures the return generated on shareholders' equity."),
    "pe_ratio": ("Is the price reasonable vs earnings (P/E)?", "A high P/E means the market is pricing in a lot of future growth."),
    "pb_ratio": ("Is the price reasonable vs book value (P/B)?", "A high P/B means the price is well above the company's net assets."),
    "valuation_vs_growth": (
        "Is the valuation reasonable given growth (PEG-like)?",
        "Weighs the P/E against actual profit growth, rather than either alone.",
    ),
    "annualized_volatility": ("Is market risk acceptable?", "Higher volatility means larger price swings to tolerate."),
    "max_drawdown": ("What is the historical downside?", "Shows the worst peak-to-trough loss an investor would have felt."),
}

# Canonical display order for the metric-backed checklist rows.
_METRIC_ORDER = [
    "revenue_growth", "profit_growth", "operating_cash_flow", "debt_to_equity",
    "interest_coverage", "roce", "roe", "pe_ratio", "pb_ratio", "valuation_vs_growth",
    "annualized_volatility", "max_drawdown",
]
_RISK_METRICS = {"annualized_volatility", "max_drawdown"}

# Why a row can be missing, per category — used only when a row IS missing, so
# the "Missing Evidence" section can say more than just "insufficient evidence".
MISSING_EVIDENCE_REASONS = {
    "financial": "Missing financial metric — the data provider (FMP) did not return this figure.",
    "risk": (
        "No usable price history — either too few daily prices were available, or the "
        "series showed no variation (a stale or thinly-traded listing)."
    ),
    "news": "Missing source — no fetched, sourced article covered this question.",
}

# The two qualitative checklist questions not backed by a single finding list —
# reuses the SAME text the agent already computed in checklist_answers (single
# source of truth for what counts as "answered"), just rendered more clearly.
_QUALITATIVE_QUESTIONS = {
    "q7": ("Does it have a durable competitive advantage (moat)?",
           "A moat protects margins and market share from competitors."),
    "q8": ("Is management trustworthy and shareholder-friendly?",
           "Management quality affects long-term execution and capital allocation."),
    "q9": ("Are there other unresolved risks in recent news?",
           "Surfaces risk signals from coverage that aren't captured by the numbers above."),
}


def build_human_checklist(report: Report) -> list[dict[str, str]]:
    """The 10-question checklist as a human-readable table.

    One row per metric actually computed (using the real finding's own value
    and healthy flag — never re-derived), plus the two news-backed qualitative
    questions using the exact text the analyst already produced. A metric that
    wasn't computed still gets a row, marked "Insufficient evidence", so the
    checklist's shape doesn't silently shrink when data is missing.
    """
    by_metric = {f.metric: f for f in report.financial_findings}
    by_metric.update({f.metric: f for f in report.risk_findings})
    rows = []
    for metric in _METRIC_ORDER:
        question, why = _METRIC_QUESTIONS[metric]
        category = "risk" if metric in _RISK_METRICS else "financial"
        finding = by_metric.get(metric)
        if finding is None:
            rows.append({"question": question, "result": "Insufficient evidence",
                         "status": "Insufficient evidence", "why_it_matters": why,
                         "category": category, "missing_reason": MISSING_EVIDENCE_REASONS[category]})
            continue
        if isinstance(finding, RiskFinding):
            elevated = (
                finding.metric == "annualized_volatility" and finding.value > config.HIGH_VOLATILITY_THRESHOLD
            ) or (
                finding.metric == "max_drawdown" and finding.value > config.CONCERNING_DRAWDOWN_THRESHOLD
            )
            status = "Elevated" if elevated else "Moderate"
        else:
            status = "Healthy" if finding.healthy else "Concern"
        rows.append({
            "question": question,
            "result": format_metric_value(metric, finding.value),
            "status": status,
            "why_it_matters": why,
            "category": category,
            "missing_reason": "",
        })

    for q_key, (question, why) in _QUALITATIVE_QUESTIONS.items():
        answer = report.checklist_answers.get(q_key, "insufficient evidence")
        insufficient = not answer or "insufficient evidence" in answer.lower()
        rows.append({
            "question": question,
            "result": "Insufficient evidence" if insufficient else answer,
            "status": "Insufficient evidence" if insufficient else "Answered",
            "why_it_matters": why,
            "category": "news",
            "missing_reason": MISSING_EVIDENCE_REASONS["news"] if insufficient else "",
        })
    return rows


def missing_evidence_rows(report: Report) -> list[dict[str, str]]:
    """The subset of the checklist that came back "Insufficient evidence", each
    with a specific reason — used for the report's "Missing Evidence" section."""
    return [row for row in build_human_checklist(report) if row["status"] == "Insufficient evidence"]


def peer_comparison_note(report: Report) -> str | None:
    """Why the peer comparison table is empty or partial, or None if it's fine.

    Distinguishes "nothing at all" from "only the target company itself" so the
    report never silently shows a table with just one column and no explanation.
    """
    if not report.peer_comparison:
        return (
            "No competitor financial data could be retrieved — competitors may not be "
            "covered by the current data plan, or the manager could not find any."
        )
    target = (report.ticker or "").upper()
    has_peer_data = any(
        any(ticker != target for ticker in values) for values in report.peer_comparison.values()
    )
    if not has_peer_data:
        return (
            "Competitor data could not be retrieved (may be outside the current data plan) — "
            "showing the target company's own metrics only."
        )
    return None


# --- Cross-check presentation: facts, sources, and status -----------------------

SOURCE_LABELS = {
    "financial": "Financial data (computed from FMP statements)",
    "news": "News coverage (fetched, sourced articles)",
    "risk": "Risk analysis (computed from price history)",
}


def contradiction_status(report: Report, contradiction: Contradiction) -> str:
    """Whether a follow-up was actually executed for this contradiction's
    target specialist, using the workflow's own record of what it re-queried
    (report.followup_targets_executed) — never guessed after the fact."""
    if contradiction.follow_up_target in report.followup_targets_executed:
        return "Follow-up executed"
    if report.contradictions_resolved >= config.MAX_FOLLOWUP_ROUNDS:
        return "Not selected for follow-up (round limit reached)"
    return "Not selected for follow-up this round"


def question_was_rewritten(report: Report) -> bool:
    """True when the panel meaningfully reworded the user's question.

    Used to show "Interpreted as: ..." only when it adds information. Casing and
    punctuation differences don't count — surfacing those would just be noise.
    """
    original, interpreted = report.question, report.interpreted_question
    if not original or not interpreted:
        return False
    return _comparable(original) != _comparable(interpreted)


def _comparable(text: str) -> str:
    """Lowercase, strip punctuation and collapse spaces, for comparing two questions."""
    kept = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text.lower())
    return " ".join(kept.split())


def crosscheck_conclusion(report: Report) -> tuple[str, str]:
    """Why the cross-check reached its verdict — ("status", "explanation").

    Important honesty rule: finding no contradiction is only meaningful if there
    was actually something to compare. With no financial findings there are no
    numbers to check the narrative against, so claiming "consistent evidence"
    would overstate what the panel did. We say so plainly instead.
    """
    has_numbers = bool(report.financial_findings)
    has_narrative = bool(report.news_findings) or bool(report.risk_findings)

    if not has_numbers or not has_narrative:
        missing = []
        if not has_numbers:
            missing.append("financial data")
        if not report.news_findings:
            missing.append("news coverage")
        if not report.risk_findings:
            missing.append("price/risk data")
        explanation = (
            "The analyst compares numeric findings against the news and risk findings. "
            f"Missing {' and '.join(missing)} means there was nothing to compare, so the "
            "absence of contradictions here is NOT evidence that the findings agree."
        )
        return ("Cross-check not possible", explanation)

    if report.contradictions_found or report.potential_tensions:
        return ("Tensions or contradictions found", "")

    consistent = (
        "The financial, news, and risk findings were compared and no tensions or "
        "contradictions were detected between them."
    )
    return ("Consistent evidence", consistent)
