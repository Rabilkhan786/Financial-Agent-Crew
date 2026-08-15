"""Looks at the share price and how it behaved, and draws the charts.

All the price maths happens in tools/kpi.py. This agent gets the finished
numbers and explains them, same rule as the fundamentals analyst.
"""

from src import charts, config, formatting, llm, state
from src.tools import kpi, market_data

log = config.get_logger(__name__)

PROMPT = """You are explaining a share price to a private investor.

Company: {company} ({ticker})
Period: {start} to {end}
Benchmark index: {benchmark}

These figures were calculated from real closing prices. Use them as given:

{facts}

Trend: {trend}
Against the index: {versus}
Risk-free rate used for the Sharpe ratio: {risk_free}

Write 2 short paragraphs in plain English:
1. How did the share perform, and how bumpy was the ride?
2. How does that compare with the index, and what does the trend say now?

Rules:
- Quote only the numbers above. Do not calculate anything new, and do not
  widen a figure into a range.
- Explain what a drawdown or a Sharpe ratio means in one short phrase.
- Do not predict where the price goes next.
"""


def run(crew_state):
    """Fetch prices, compute the KPIs, draw the charts, then explain them."""
    ticker = crew_state["ticker"]
    log.info("data_analyst: starting %s", ticker)

    market = market_data.fetch_market_data(
        ticker, crew_state.get("start_date"), crew_state.get("end_date"))

    if market["prices"].empty:
        message = market["error"] or f"No price data for {ticker}."
        log.warning("data_analyst: %s", message)
        return {
            "analysis": {"available": False, "note": message},
            "conversation_log": [state.note("data_analyst", message)],
            "errors": [message],
        }

    computed = kpi.compute_all(market["prices"], market["benchmark_prices"],
                              risk_free_rate=config.RISK_FREE_RATE)

    drawn = charts.build_all(crew_state.get("fundamentals", {}),
                             computed["series"], ticker)

    benchmark = computed["benchmark"]
    interpretation = llm.ask(PROMPT.format(
        company=crew_state.get("company") or ticker,
        ticker=ticker,
        start=crew_state.get("start_date"),
        end=crew_state.get("end_date"),
        benchmark=market["benchmark_symbol"],
        facts=formatting.facts_block(computed["latest"]),
        trend=computed["trend"],
        versus=benchmark["verdict"] if benchmark else "no overlapping index data",
        risk_free=f"{config.RISK_FREE_RATE:.1%}",
    ))

    summary = (f"Priced {len(market['prices'])} trading days against "
               f"{market['benchmark_symbol']}. Drew {len(drawn)} charts.")
    log.info("data_analyst: %s", summary)

    return {
        "analysis": {
            "available": True,
            "kpis": computed["latest"],
            "trend": computed["trend"],
            "benchmark": benchmark,
            "benchmark_symbol": market["benchmark_symbol"],
            "risk_free_rate": config.RISK_FREE_RATE,
            "unavailable": computed["unavailable"],
            "price_series": computed["series"],
            "charts": drawn,
            "interpretation": interpretation,
        },
        "conversation_log": [state.note("data_analyst", summary)],
    }
