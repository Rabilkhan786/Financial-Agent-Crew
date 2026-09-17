"""Formatting helpers shared by the UI and agents."""

PERCENT_METRICS = {
    "revenue_growth_yoy",
    "revenue_cagr",
    "operating_margin",
    "net_margin",
    "return_on_equity",
    "return_on_capital_employed",
    "total_return",
    "annualised_return",
    "volatility",
    "max_drawdown",
}

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
    "annualised_return": "Annualised return",
    "volatility": "Volatility",
    "max_drawdown": "Maximum drawdown",
    "sharpe_ratio": "Sharpe ratio",
    "ma_50": "50-day moving average",
    "ma_200": "200-day moving average",
    "last_close": "Last close",
}

STATEMENT_SOURCE = "Yahoo Finance statements"
PRICE_SOURCE = "Yahoo Finance closing prices"

EVIDENCE = {
    "revenue_growth_yoy": (
        "latest fiscal year",
        STATEMENT_SOURCE,
        "(revenue - prior revenue) / prior revenue",
    ),
    "revenue_cagr": (
        "latest 3 fiscal years",
        STATEMENT_SOURCE,
        "(latest revenue / revenue 3 years ago) ** (1/3) - 1",
    ),
    "operating_margin": (
        "latest fiscal year",
        STATEMENT_SOURCE,
        "operating income / revenue",
    ),
    "net_margin": (
        "latest fiscal year",
        STATEMENT_SOURCE,
        "net income / revenue",
    ),
    "cash_conversion": (
        "latest fiscal year",
        STATEMENT_SOURCE,
        "operating cash flow / net income",
    ),
    "free_cash_flow": (
        "latest fiscal year",
        STATEMENT_SOURCE,
        "operating cash flow - |capital expenditure|",
    ),
    "debt_to_equity": (
        "latest fiscal year",
        STATEMENT_SOURCE,
        "total debt / total equity",
    ),
    "interest_coverage": (
        "latest fiscal year",
        STATEMENT_SOURCE,
        "EBIT / |interest expense|",
    ),
    "return_on_capital_employed": (
        "latest fiscal year",
        STATEMENT_SOURCE,
        "EBIT / (total assets - current liabilities)",
    ),
    "return_on_equity": (
        "latest fiscal year",
        STATEMENT_SOURCE,
        "net income / total equity",
    ),
    "total_return": (
        "selected period",
        PRICE_SOURCE,
        "last close / first close - 1",
    ),
    "annualised_return": (
        "selected period",
        PRICE_SOURCE,
        "(last close / first close) ** (1 / years) - 1",
    ),
    "volatility": (
        "selected period",
        PRICE_SOURCE,
        "daily return standard deviation * sqrt(252)",
    ),
    "max_drawdown": (
        "selected period",
        PRICE_SOURCE,
        "minimum(close / running peak - 1)",
    ),
    "sharpe_ratio": (
        "selected period",
        PRICE_SOURCE,
        "(annualised return - risk-free rate) / volatility",
    ),
    "ma_50": (
        "last 50 trading days",
        PRICE_SOURCE,
        "50-day rolling average",
    ),
    "ma_200": (
        "last 200 trading days",
        PRICE_SOURCE,
        "200-day rolling average",
    ),
    "last_close": ("latest trading day", PRICE_SOURCE, "closing price"),
}


def label(name):
    """Return a readable label for a metric name."""
    return LABELS.get(name, name.replace("_", " ").capitalize())


def evidence_for(name):
    """Return the period, source, and formula for one metric."""
    period, source, formula = EVIDENCE.get(name, ("-", "-", "-"))
    return {"period": period, "source": source, "formula": formula}


def money(value, currency=None):
    """Format a monetary value for display."""
    if value is None:
        return "unavailable"

    prefix = f"{currency} " if currency else ""
    if abs(value) >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:,.2f}bn"
    if abs(value) >= 1_000_000:
        return f"{prefix}{value / 1_000_000:,.1f}m"
    return f"{prefix}{value:,.2f}"


def metric(name, value, currency=None):
    """Format one calculated metric for display or a prompt."""
    if value is None:
        return "unavailable"
    if name in PERCENT_METRICS:
        return f"{value:.1%}"
    if name == "free_cash_flow":
        return money(value, currency)
    return f"{value:.2f}"


def facts_block(metrics, currency=None):
    """Convert calculated metrics into prompt-ready bullet points."""
    return "\n".join(
        f"- {label(name)}: {metric(name, value, currency)}"
        for name, value in metrics.items()
    )


def red_flags_block(flags):
    """Convert deterministic red flags into prompt-ready bullet points."""
    if not flags:
        return "- none"
    return "\n".join(
        f"- [{flag['severity']}] {flag['message']}"
        for flag in flags
    )
