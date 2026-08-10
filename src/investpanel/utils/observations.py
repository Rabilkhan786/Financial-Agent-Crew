"""Surface material findings the fixed checklist never asks about.

CHANGE 5: the 10 questions are a floor, not a ceiling. These detectors look at the
numbers the specialists already computed and flag things a reader would want to
know even though no checklist question covers them — margin collapse, profit that
isn't turning into cash, a valuation priced for growth that isn't happening.

Deterministic on purpose. An LLM asked to "find anything else interesting" produces
plausible-sounding commentary with no evidence behind it; each function here fires
on a concrete comparison between computed values and cites the numbers it used.
"""

from investpanel import config
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding
from investpanel.models.observation import Observation
from investpanel.utils.report_format import format_metric_value

# A margin this much below the others suggests costs are eating the business.
_MARGIN_COLLAPSE_RATIO = 0.25   # net margin under a quarter of gross margin
_HIGH_DRAWDOWN_VS_VOL = 1.5     # drawdown much deeper than volatility implies


def _by_metric(findings: list) -> dict:
    return {f.metric: f for f in findings}


def _value(findings: dict, metric: str):
    finding = findings.get(metric)
    return finding.value if finding else None


def financial_observations(financial: list[FinancialFinding]) -> list[Observation]:
    """Material things in the numbers that the checklist doesn't ask about."""
    found: list[Observation] = []
    metrics = _by_metric(financial)

    gross = _value(metrics, "gross_margin")
    net = _value(metrics, "net_margin")
    operating = _value(metrics, "operating_margin")

    # Costs consuming the business: healthy gross margin, very little left at the end.
    if gross and net is not None and gross > 0 and net < gross * _MARGIN_COLLAPSE_RATIO:
        found.append(Observation(
            source="financial",
            title="Most of the gross margin is consumed before it reaches profit",
            detail=(
                "Gross margin is healthy but very little survives to the bottom line, "
                "which points at operating costs, interest, or one-off charges rather "
                "than at pricing."
            ),
            severity="watch",
            evidence=[
                f"gross margin {format_metric_value('gross_margin', gross)}",
                f"net margin {format_metric_value('net_margin', net)}",
            ],
        ))

    # Operating losses — the core business doesn't wash its own face.
    if operating is not None and operating < 0:
        found.append(Observation(
            source="financial",
            title="The core business is loss-making at the operating level",
            detail="Operating margin is negative, so trading costs exceed gross profit "
                   "before financing and tax are even considered.",
            severity="concern",
            evidence=[f"operating margin {format_metric_value('operating_margin', operating)}"],
        ))

    # Profit that isn't becoming cash — the classic accounting warning sign.
    conversion = _value(metrics, "cash_conversion")
    if conversion is not None and conversion < config.HEALTHY_CASH_CONVERSION_MIN:
        found.append(Observation(
            source="financial",
            title="Reported profit is not converting into cash",
            detail=(
                "Operating cash flow is materially below reported net income. That gap "
                "is worth explaining — it can be timing, or it can be earnings quality."
            ),
            severity="concern" if conversion < 0.5 else "watch",
            evidence=[f"cash conversion {format_metric_value('cash_conversion', conversion)}"],
        ))

    # Growth-priced valuation with no growth behind it.
    pe = _value(metrics, "pe_ratio")
    revenue_growth = _value(metrics, "revenue_growth")
    if pe is not None and pe > config.HEALTHY_PE_MAX and revenue_growth is not None and revenue_growth <= 0:
        found.append(Observation(
            source="financial",
            title="Priced for growth the revenue line isn't showing",
            detail="The earnings multiple sits above the comfortable range while revenue "
                   "is flat or shrinking, so the price depends on a recovery that hasn't "
                   "appeared in the numbers yet.",
            severity="concern",
            evidence=[
                f"P/E {format_metric_value('pe_ratio', pe)}",
                f"revenue growth {format_metric_value('revenue_growth', revenue_growth)}",
            ],
        ))

    # Debt that the earnings barely cover.
    coverage = _value(metrics, "interest_coverage")
    if coverage is not None and coverage < config.HEALTHY_INTEREST_COVERAGE_MIN:
        found.append(Observation(
            source="financial",
            title="Interest costs are only thinly covered by operating profit",
            detail="A dip in earnings would put debt servicing under real pressure.",
            severity="concern",
            evidence=[f"interest coverage {format_metric_value('interest_coverage', coverage)}"],
        ))

    return found


def risk_observations(risk: list[RiskFinding]) -> list[Observation]:
    """Material things in the price behaviour beyond the two headline numbers."""
    found: list[Observation] = []
    metrics = _by_metric(risk)
    vol = _value(metrics, "annualized_volatility")
    drawdown = _value(metrics, "max_drawdown")

    # A fall much deeper than the day-to-day wobble implies means the damage came
    # from events, not from ordinary noise.
    if vol and drawdown and vol > 0 and drawdown > vol * _HIGH_DRAWDOWN_VS_VOL:
        found.append(Observation(
            source="risk",
            title="The worst fall is deeper than day-to-day volatility suggests",
            detail=(
                "The peak-to-trough drop is much larger than the typical daily movement, "
                "which usually means specific events drove it rather than general noise."
            ),
            severity="watch",
            evidence=[
                f"annualized volatility {format_metric_value('annualized_volatility', vol)}",
                f"max drawdown {format_metric_value('max_drawdown', drawdown)}",
            ],
        ))
    return found


def news_observations(news: list[NewsFinding]) -> list[Observation]:
    """Sourced news items that don't map onto a checklist question.

    Only high-relevance, untagged articles qualify — anything tagged moat,
    management or risk is already answering Q7-Q9, so repeating it here would
    just be noise.
    """
    found = []
    for item in news:
        if item.relevance == "high" and item.checklist_question is None:
            found.append(Observation(
                source="news",
                title=item.headline,
                detail=item.summary,
                severity="info",
                evidence=[str(item.source_url)],
            ))
    return found


def collect_observations(
    financial: list[FinancialFinding],
    news: list[NewsFinding],
    risk: list[RiskFinding],
) -> list[Observation]:
    """Everything material the checklist didn't ask about, worst first."""
    found = financial_observations(financial) + risk_observations(risk) + news_observations(news)
    order = {"concern": 0, "watch": 1, "info": 2}
    found.sort(key=lambda o: order[o.severity])
    return found
