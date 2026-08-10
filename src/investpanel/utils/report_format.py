"""Human-readable number formatting for the report and Streamlit UI.

The agents and models store raw numeric values (e.g. ``pe_ratio=19.8571``) because
that's what's actually computed and easiest to test. This module is the ONE place
that turns those raw values into the strings a reader sees (``"P/E Ratio: 19.86×"``)
— reused by app.py, report_export.py, and run.py so formatting never drifts
between the three. Every function here is pure: given the same number, it always
returns the same string. No values are changed, only how they're displayed.
"""

# Human-readable label for each metric key, used instead of the raw field name.
METRIC_LABELS = {
    "revenue_growth": "Revenue Growth",
    "profit_growth": "Profit Growth",
    "operating_cash_flow": "Operating Cash Flow",
    "debt_to_equity": "Debt-to-Equity",
    "interest_coverage": "Interest Coverage",
    "roce": "ROCE",
    "roe": "ROE",
    "pe_ratio": "P/E Ratio",
    "pb_ratio": "P/B Ratio",
    "valuation_vs_growth": "Valuation vs Growth (PEG-like)",
    "gross_margin": "Gross Margin",
    "operating_margin": "Operating Margin",
    "net_margin": "Net Margin",
    "cash_conversion": "Cash Conversion (OCF / Net Income)",
    "annualized_volatility": "Annualized Volatility",
    "max_drawdown": "Maximum Drawdown",
}

# Metrics whose raw value is a fraction (0.21) that should be shown as a plain
# percent (21%, no +/- sign — it's a return level, not a change).
_FRACTION_AS_PLAIN_PERCENT_METRICS = {
    "roce", "roe", "gross_margin", "operating_margin", "net_margin",
}
# Metrics already stored as a percent number (19.22, not 0.1922).
_ALREADY_PERCENT_METRICS = {"revenue_growth", "profit_growth"}
# Metrics shown as a "N×" multiple.
_MULTIPLE_METRICS = {"pe_ratio", "pb_ratio", "debt_to_equity"}
_TIMES_METRICS = {"interest_coverage"}


def format_currency(value: float) -> str:
    """1_234_567_890 -> "$1.23B". Handles negative values and small numbers too."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e12:
        return f"{sign}${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"{sign}${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.2f}M"
    if v >= 1e3:
        return f"{sign}${v / 1e3:.2f}K"
    return f"{sign}${v:,.2f}"


def format_percent(value: float, decimals: int = 2, signed: bool = True) -> str:
    """19.22 -> "+19.22%". Set signed=False to omit the leading "+" on positives."""
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_multiple(value: float, decimals: int = 2) -> str:
    """19.8571 -> "19.86×"."""
    return f"{value:.{decimals}f}×"


def format_times(value: float, decimals: int = 0) -> str:
    """76.0 -> "76×" (interest coverage, "how many times over")."""
    return f"{value:.{decimals}f}×"


def format_ratio_plain(value: float, decimals: int = 2) -> str:
    """0.6 -> "0.60" — a plain number, no unit (e.g. a PEG-like ratio)."""
    return f"{value:.{decimals}f}"


def format_metric_label(metric: str) -> str:
    """The human-readable name for a metric key, falling back to a title-cased guess."""
    return METRIC_LABELS.get(metric, metric.replace("_", " ").title())


def format_metric_value(metric: str, value: float) -> str:
    """Format one finding's raw value the way a reader expects for that metric.

    This is metric-aware (not just unit-aware) because the same raw shape (a
    plain float) means different things for different metrics — a P/E of 19.86
    is a multiple, an ROE of 0.209 is a percent, a revenue_growth of 19.22 is
    already a percent number. Getting this right is the whole point of the file.
    """
    if metric in _ALREADY_PERCENT_METRICS:
        return format_percent(value) + " YoY"
    if metric == "max_drawdown":
        return format_drawdown(value)
    if metric == "annualized_volatility":
        return format_volatility(value)
    if metric in _FRACTION_AS_PLAIN_PERCENT_METRICS:
        return format_percent(value * 100, decimals=1, signed=False)
    if metric == "operating_cash_flow":
        return format_currency(value)
    if metric in _MULTIPLE_METRICS:
        return format_multiple(value)
    if metric in _TIMES_METRICS:
        return format_times(value)
    if metric == "cash_conversion":
        return format_multiple(value)
    if metric == "valuation_vs_growth":
        return format_ratio_plain(value)
    # Unknown metric: show a plain, still-rounded number rather than raw Python repr.
    return f"{value:,.2f}"


def format_drawdown(value: float) -> str:
    """0.26 (a positive fraction meaning "26% below peak") -> "-26.0%"."""
    return f"-{value * 100:.1f}%"


def format_volatility(value: float) -> str:
    """0.3987 -> "39.9%"."""
    return f"{value * 100:.1f}%"
