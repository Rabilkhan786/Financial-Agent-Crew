"""Analyze stock-price performance and create charts."""

from src.components import config
from src.components.logging import get_logger
from src.core import llm
from src.tools import kpi, market_data
from src.utils import charts, formatting

log = get_logger(__name__)

PROMPT = """You are a data analyst.

Company: {company} ({ticker})
Period: {start} to {end}
Benchmark: {benchmark}

Calculated price metrics:
{facts}

Trend: {trend}
Benchmark comparison: {comparison}

Write two short paragraphs explaining performance, risk, trend, and benchmark comparison.
Use only the supplied numbers. Do not predict future prices.
"""


def run(crew_state):
    """Fetch prices, calculate KPIs, create charts, and explain the results."""
    ticker = crew_state["ticker"]
    market = market_data.fetch_market_data(
        ticker,
        crew_state.get("start_date"),
        crew_state.get("end_date"),
    )

    if market["prices"].empty:
        message = market.get("error") or f"No price data available for {ticker}."
        return {
            "analysis": {
                "available": False,
                "note": message,
            },
            "conversation_log": [
                {"agent": "data_analyst", "message": message}
            ],
            "errors": [message],
        }

    computed = kpi.compute_all(
        market["prices"],
        market["benchmark_prices"],
        risk_free_rate=config.RISK_FREE_RATE,
    )

    chart_paths = charts.build_all(
        crew_state.get("fundamentals", {}),
        computed["series"],
        ticker,
    )

    benchmark = computed.get("benchmark")
    comparison = (
        benchmark.get("verdict")
        if benchmark
        else "Benchmark comparison unavailable."
    )

    interpretation = llm.ask(
        PROMPT.format(
            company=crew_state.get("company") or ticker,
            ticker=ticker,
            start=crew_state.get("start_date"),
            end=crew_state.get("end_date"),
            benchmark=market["benchmark_symbol"],
            facts=formatting.facts_block(computed["latest"]),
            trend=computed["trend"],
            comparison=comparison,
        )
    )

    message = (
        f"Analyzed {len(market['prices'])} trading days against "
        f"{market['benchmark_symbol']}."
    )
    log.info("%s: %s", ticker, message)

    return {
        "analysis": {
            "available": True,
            "kpis": computed["latest"],
            "trend": computed["trend"],
            "benchmark": benchmark,
            "benchmark_symbol": market["benchmark_symbol"],
            "price_series": computed["series"],
            "charts": chart_paths,
            "interpretation": interpretation,
        },
        "conversation_log": [
            {"agent": "data_analyst", "message": message}
        ],
    }
