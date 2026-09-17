"""Create charts used by the Streamlit app and PDF report."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from src.components import config  # noqa: E402
from src.components.logging import get_logger  # noqa: E402
from src.tools import ratios  # noqa: E402

log = get_logger(__name__)


def _save(figure, ticker, name):
    """Save one chart and return its file path."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUT_DIR / f"{ticker.replace('.', '_')}_{name}.png"
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return str(path)


def _years(series):
    """Return readable year labels for a Series index."""
    return [
        str(item.year) if hasattr(item, "year") else str(item)
        for item in series.index
    ]


def _revenue_profit(series, ticker, currency):
    """Create the revenue and net-profit chart."""
    revenue = series.get("revenue")
    profit = series.get("net_income")
    if revenue is None or profit is None:
        return None

    revenue = revenue.tail(4)
    profit = profit.tail(4)
    positions = range(len(revenue))

    figure, axes = plt.subplots(figsize=(7.5, 3.6))
    axes.bar(
        [position - 0.2 for position in positions],
        revenue.values,
        width=0.4,
        label="Revenue",
    )
    axes.bar(
        [position + 0.2 for position in positions],
        profit.values,
        width=0.4,
        label="Net profit",
    )
    axes.set_title(f"Revenue and net profit ({currency or 'reported currency'})")
    axes.set_xticks(list(positions))
    axes.set_xticklabels(_years(revenue))
    axes.legend()
    return _save(figure, ticker, "revenue_profit")


def _margins(series, ticker):
    """Create the operating- and net-margin trend chart."""
    operating = series.get("operating_margin")
    net = series.get("net_margin")
    if operating is None and net is None:
        return None

    figure, axes = plt.subplots(figsize=(7.5, 3.6))
    if operating is not None:
        axes.plot(
            _years(operating),
            (operating * 100).values,
            marker="o",
            label="Operating margin",
        )
    if net is not None:
        axes.plot(
            _years(net),
            (net * 100).values,
            marker="o",
            label="Net margin",
        )
    axes.set_title("Margin trend")
    axes.set_ylabel("%")
    axes.legend()
    return _save(figure, ticker, "margins")


def _cash_profit(series, ticker, currency):
    """Create the operating-cash-flow versus net-profit chart."""
    cash = series.get("operating_cash_flow")
    profit = series.get("net_income")
    if cash is None or profit is None:
        return None

    positions = range(len(cash))
    figure, axes = plt.subplots(figsize=(7.5, 3.6))
    axes.bar(
        [position - 0.2 for position in positions],
        cash.values,
        width=0.4,
        label="Operating cash flow",
    )
    axes.bar(
        [position + 0.2 for position in positions],
        profit.values,
        width=0.4,
        label="Net profit",
    )
    axes.set_title(f"Cash flow vs profit ({currency or 'reported currency'})")
    axes.set_xticks(list(positions))
    axes.set_xticklabels(_years(cash))
    axes.legend()
    return _save(figure, ticker, "cash_vs_profit")


def _debt(series, ticker):
    """Create the debt-to-equity trend chart."""
    leverage = series.get("debt_to_equity")
    if leverage is None or leverage.dropna().empty:
        return None

    figure, axes = plt.subplots(figsize=(7.5, 3.6))
    axes.plot(_years(leverage), leverage.values, marker="o")
    axes.axhline(
        ratios.DEBT_TO_EQUITY_CEILING,
        linestyle="--",
        linewidth=1,
    )
    axes.set_title("Debt to equity")
    return _save(figure, ticker, "debt")


def _price(series, ticker):
    """Create the closing-price and moving-average chart."""
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
    return _save(figure, ticker, "price")


def build_all(fundamentals, price_series, ticker):
    """Create each chart that has enough source data."""
    series = fundamentals.get("series", {}) or {}
    currency = fundamentals.get("currency")

    output = {
        "revenue_profit": _revenue_profit(series, ticker, currency),
        "margins": _margins(series, ticker),
        "cash_vs_profit": _cash_profit(series, ticker, currency),
        "debt": _debt(series, ticker),
        "price": _price(price_series or {}, ticker),
    }

    output = {name: path for name, path in output.items() if path}
    log.info("Created %d charts for %s", len(output), ticker)
    return output
