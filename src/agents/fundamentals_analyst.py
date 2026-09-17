"""Analyze company financial statements and explain the results."""

import datetime as dt

from src.components.logging import get_logger
from src.core import llm
from src.tools import market_data, ratios, statements
from src.utils import formatting

log = get_logger(__name__)

PROMPT = """You are a fundamentals analyst.

Company: {company} ({ticker})
Currency: {currency}
Years available: {years}

Calculated metrics:
{facts}

Valuation:
{valuation}

Red flags:
{flags}

Missing data:
{gaps}

{revision}

Write four short paragraphs covering growth, profitability, cash/debt, and valuation.
Use only the supplied numbers. Do not calculate new values and do not give buy/sell advice.
"""


def run(crew_state):
    """Fetch statements, calculate ratios, and explain them."""
    ticker = crew_state["ticker"]
    fetched = statements.fetch_statements(ticker)

    if fetched["data"].empty:
        message = fetched.get("error") or f"No statement data available for {ticker}."
        return {
            "fundamentals": {
                "available": False,
                "note": message,
                "data_source": "unavailable",
            },
            "conversation_log": [
                {"agent": "fundamentals_analyst", "message": message}
            ],
            "errors": [message],
        }

    profile = market_data.fetch_profile(ticker)
    statement_data = fetched["data"]

    history_start = (
        statement_data.index[0] - dt.timedelta(days=60)
    ).date().isoformat()
    prices = market_data.fetch_prices(ticker, history_start, None)
    valuation_history = market_data.valuation_history(prices, statement_data)

    computed = ratios.compute_all(
        statement_data,
        pe_current=profile.get("trailing_pe"),
        pe_history=valuation_history["pe_history"],
        pb_current=profile.get("price_to_book"),
        pb_history=valuation_history["pb_history"],
    )

    valuation_lines = []
    for name in ("pe", "pb"):
        value = computed["valuation"].get(name)
        label = "P/E" if name == "pe" else "P/B"
        if value:
            valuation_lines.append(
                f"- {label}: {value['current']:.1f} current, "
                f"{value['median']:.1f} historical median, {value['verdict']}"
            )
        else:
            valuation_lines.append(f"- {label}: unavailable")

    flags = computed["red_flags"]
    flag_text = "\n".join(
        f"- [{flag['severity']}] {flag['message']}"
        for flag in flags
    ) or "- none"

    revision = ""
    if crew_state.get("revision_target") == "fundamentals_analyst":
        revision = "Reviewer feedback: " + crew_state.get("revision_reason", "")

    company = crew_state.get("company") or profile.get("name") or ticker
    interpretation = llm.ask(
        PROMPT.format(
            company=company,
            ticker=ticker,
            currency=fetched.get("currency") or "unknown",
            years=fetched["years"],
            facts=formatting.facts_block(
                computed["latest"],
                fetched.get("currency"),
            ),
            valuation="\n".join(valuation_lines),
            flags=flag_text,
            gaps=statements.describe_gaps(fetched),
            revision=revision,
        )
    )

    message = (
        f"Analyzed {fetched['years']} years of statements and found "
        f"{len(flags)} red flag(s)."
    )
    log.info("%s: %s", ticker, message)

    return {
        "fundamentals": {
            "available": True,
            "metrics": computed["latest"],
            "series": computed["series"],
            "valuation": computed["valuation"],
            "red_flags": flags,
            "unavailable": computed["unavailable"],
            "currency": fetched.get("currency"),
            "years": fetched["years"],
            "period_end": fetched.get("period_end"),
            "data_note": statements.describe_gaps(fetched),
            "data_source": fetched.get("data_source"),
            "interpretation": interpretation,
        },
        "company": company,
        "conversation_log": [
            {"agent": "fundamentals_analyst", "message": message}
        ],
    }
