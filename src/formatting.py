"""Turning numbers into readable text.

One place for this so the app, the PDF and the agents all print a ratio the
same way. Without it the same formatting rules get copied into three files and
drift apart.
"""

# Metrics that read better as percentages than as raw decimals.
PERCENT_METRICS = {
    "revenue_growth_yoy", "revenue_cagr", "operating_margin", "net_margin",
    "return_on_equity", "return_on_capital_employed",
    "total_return", "annualised_return", "volatility", "max_drawdown",
}

# Friendly names for the report and the app.
LABELS = {
    "revenue_growth_yoy": "Revenue growth (latest year)",
    "revenue_cagr": "Revenue CAGR (3 years)",
    "operating_margin": "Operating margin",
    "net_margin": "Net margin",
    "cash_conversion": "Cash conversion (OCF / net profit)",
    "free_cash_flow": "Free cash flow",
    "debt_to_equity": "Debt to equity",
    "interest_coverage": "Interest coverage",
    "return_on_capital_employed": "Return on capital employed",
    "return_on_equity": "Return on equity",
    "total_return": "Total return",
    "annualised_return": "Annualised return (CAGR)",
    "volatility": "Volatility (annualised)",
    "max_drawdown": "Maximum drawdown",
    "sharpe_ratio": "Sharpe ratio",
    "ma_50": "50-day moving average",
    "ma_200": "200-day moving average",
    "last_close": "Last close",
}


def label(name):
    return LABELS.get(name, name.replace("_", " ").capitalize())


def money(value, currency=None):
    """Large amounts shortened to billions or millions."""
    if value is None:
        return "unavailable"
    unit = f"{currency} " if currency else ""
    if abs(value) >= 1_000_000_000:
        return f"{unit}{value / 1_000_000_000:,.2f}bn"
    if abs(value) >= 1_000_000:
        return f"{unit}{value / 1_000_000:,.1f}m"
    return f"{unit}{value:,.2f}"


def metric(name, value, currency=None):
    """One metric as text. Anything missing says so instead of showing a number."""
    if value is None:
        return "unavailable"
    if name in PERCENT_METRICS:
        return f"{value:.1%}"
    if name == "free_cash_flow":
        return money(value, currency)
    return f"{value:.2f}"


def facts_block(metrics, currency=None):
    """The metrics as a plain list, ready to paste into a prompt.

    This is what the model is allowed to talk about. It gets the numbers already
    worked out, so it never has to do arithmetic of its own.
    """
    lines = []
    for name, value in metrics.items():
        lines.append(f"- {label(name)}: {metric(name, value, currency)}")
    return "\n".join(lines)
