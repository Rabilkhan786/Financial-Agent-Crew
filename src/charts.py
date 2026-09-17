"""Draw the charts used by the app and PDF report."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from src import config  # noqa: E402
from src.tools import ratios  # noqa: E402

log = config.get_logger(__name__)


def save(figure, ticker, name):
    """Save a chart in the output folder and return its path."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUT_DIR / f"{ticker.replace('.', '_')}_{name}.png"
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return str(path)


def year_labels(series):
    """Return fiscal-year labels for a Series index."""
    return [str(item.year) if hasattr(item, "year") else str(item) for item in series.index]


def revenue_and_profit(series, ticker, currency):
    """Draw revenue and net profit for the latest four years."""
    revenue = series.get("revenue")
    profit = series.get("net_income")
    if revenue is None or profit is None:
        return None

    revenue = revenue.tail(4)
    profit = profit.tail(4)
    spots = range(len(revenue))

    figure, axes = plt.subplots(figsize=(7.5, 3.6))
    axes.bar([spot - 0.2 for spot in spots], revenue.values, width=0.4, label="Revenue")
    axes.bar([spot + 0.2 for spot in spots], profit.values, width=0.4, label="Net profit")
    axes.set_title(f"Revenue and net profit ({currency or 'reported currency'})")
    axes.set_xticks(list(spots))
    axes.set_xticklabels(year_labels(revenue))
    axes.legend()
    return save(figure, ticker, "revenue_profit")


def margin_trend(series, ticker):
    """Draw operating and net margin over time."""
    operating = series.get("operating_margin")
    net = series.get("net_margin")
    if operating is None and net is None:
        return None

    figure, axes = plt.subplots(figsize=(7.5, 3.6))
    if operating is not None:
        axes.plot(
            year_labels(operating),
            (operating * 100).values,
            marker="o",
            label="Operating margin",
        )
    if net is not None:
        axes.plot(
            year_labels(net),
            (net * 100).values,
            marker="o",
            label="Net margin",
        )
    axes.set_title("Margin trend")
    axes.set_ylabel("%")
    axes.legend()
    return save(figure, ticker, "margins")


def cash_vs_profit(series, ticker, currency):
    """Draw operating cash flow beside net profit."""
    cash = series.get("operating_cash_flow")
    profit = series.get("net_income")
    if cash is None or profit is None:
        return None

    spots = range(len(cash))
    figure, axes = plt.subplots(figsize=(7.5, 3.6))
    axes.bar([spot - 0.2 for spot in spots], cash.values, width=0.4, label="Operating cash flow")
    axes.bar([spot + 0.2 for spot in spots], profit.values, width=0.4, label="Net profit")
    axes.set_title(f"Cash flow vs profit ({currency or 'reported currency'})")
    axes.set_xticks(list(spots))
    axes.set_xticklabels(year_labels(cash))
    axes.legend()
    return save(figure, ticker, "cash_vs_profit")


def debt_trend(series, ticker):
    """Draw debt to equity and the same threshold used by the red-flag rule."""
    leverage = series.get("debt_to_equity")
    if leverage is None or leverage.dropna().empty:
        return None

    figure, axes = plt.subplots(figsize=(7.5, 3.6))
    axes.plot(year_labels(leverage), leverage.values, marker="o")
    axes.axhline(
        ratios.DEBT_TO_EQUITY_CEILING,
        linestyle="--",
        linewidth=1,
        color="grey",
    )
    axes.set_title("Debt to equity (dashed line = the level we flag)")
    return save(figure, ticker, "debt")


def price_with_averages(series, ticker):
    """Draw closing price with available moving averages."""
    close = series.get("close")
    if close is None or close.empty:
        return None

    figure, axes = plt.subplots(figsize=(7.5, 3.6))
    axes.plot(close.index, close.values, linewidth=1.2, label="Close")
    for name in ("ma_50", "ma_200"):
        average = series.get(name)
        if average is not None and not average.dropna().empty:
            axes.plot(
                average.index,
                average.values,
                linewidth=1.1,
                label=name.replace("ma_", "") + "-day average",
            )
    axes.set_title("Price with moving averages")
    axes.legend()
    figure.autofmt_xdate()
    return save(figure, ticker, "price")


def build_all(fundamentals, price_series, ticker):
    """Draw every chart for which the required data is available."""
    series = fundamentals.get("series", {}) or {}
    currency = fundamentals.get("currency")

    charts = {
        "revenue_profit": revenue_and_profit(series, ticker, currency),
        "margins": margin_trend(series, ticker),
        "cash_vs_profit": cash_vs_profit(series, ticker, currency),
        "debt": debt_trend(series, ticker),
        "price": price_with_averages(price_series or {}, ticker),
    }
    drawn = {name: path for name, path in charts.items() if path}
    log.info("charts: drew %d of 5 for %s", len(drawn), ticker)
    return drawn
