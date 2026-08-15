"""Reads the financial statements and says what the numbers mean.

Every ratio is calculated in `tools/ratios.py` first. This agent only receives
the finished numbers and explains them. It is never asked to divide anything,
because a model doing arithmetic cannot be checked and a wrong figure in a
financial report is worse than no figure at all.
"""

from src import config, formatting, llm, state
from src.tools import market_data, ratios, statements

log = config.get_logger(__name__)

PROMPT = """You are a fundamentals analyst writing for a private investor.

Company: {company} ({ticker})
Reporting currency: {currency}
Financial years covered: {years}

These figures were calculated from the audited statements. They are correct.
Use them exactly as given and do not calculate any new numbers:

{facts}

Valuation against the company's own history:
{valuation}

Automated checks flagged these issues:
{flags}

Could not be calculated (the data provider does not report them):
{unavailable}

{revision}

Write 4 short paragraphs, in plain English, no jargon:
1. Growth - is revenue growing, and how fast?
2. Profitability - are margins healthy, improving or slipping?
3. Cash and balance sheet - does profit turn into cash, and is the debt safe?
4. Valuation - is the share expensive or cheap against its own history?

Rules:
- Quote only the numbers listed above. Never invent or estimate a figure, and
  never widen one into a range.
- If something is listed as unavailable, say it is unavailable. Do not guess it.
- Mention every flagged issue. Do not soften them.
- No recommendation to buy or sell. That is not your job here.
"""


def _valuation_text(valuation):
    lines = []
    for name in ("pe", "pb"):
        result = valuation.get(name)
        title = "P/E" if name == "pe" else "P/B"
        if result is None:
            lines.append(f"- {title}: not enough history to compare")
        else:
            lines.append(f"- {title}: {result['current']:.1f} today, "
                         f"{result['median']:.1f} median, {result['verdict']}")
    return "\n".join(lines)


def run(crew_state):
    """Fetch the statements, compute the ratios, then explain them."""
    ticker = crew_state["ticker"]
    log.info("fundamentals_analyst: starting %s", ticker)

    fetched = statements.fetch_statements(ticker)
    if fetched["data"].empty:
        message = fetched["error"] or f"No statement data available for {ticker}."
        log.warning("fundamentals_analyst: %s", message)
        return {
            "fundamentals": {"available": False, "note": message},
            "conversation_log": [state.note("fundamentals_analyst", message)],
            "errors": [message],
        }

    profile = market_data.fetch_profile(ticker)
    prices = market_data.fetch_prices(ticker)
    valuation_input = market_data.valuation_history(prices, fetched["data"])

    computed = ratios.compute_all(
        fetched["data"],
        pe_current=profile.get("trailing_pe"),
        pe_history=valuation_input["pe_history"],
        pb_current=profile.get("price_to_book"),
        pb_history=valuation_input["pb_history"],
    )

    currency = fetched["currency"]
    flags = computed["red_flags"]
    revision = ""
    if crew_state.get("revision_target") == "fundamentals_analyst":
        revision = ("The reviewer sent this back with a specific request. "
                    f"Address it directly: {crew_state.get('revision_reason', '')}")

    interpretation = llm.ask(PROMPT.format(
        company=crew_state.get("company") or profile.get("name") or ticker,
        ticker=ticker,
        currency=currency or "unknown",
        years=fetched["years"],
        facts=formatting.facts_block(computed["latest"], currency),
        valuation=_valuation_text(computed["valuation"]),
        flags="\n".join(f"- [{f['severity']}] {f['message']}" for f in flags) or "- none",
        unavailable=", ".join(computed["unavailable"]) or "nothing - all metrics available",
        revision=revision,
    ))

    summary = (f"Read {fetched['years']} years of statements. "
               f"{len(flags)} red flag(s). "
               f"{len(computed['unavailable'])} metric(s) unavailable.")
    log.info("fundamentals_analyst: %s", summary)

    return {
        "fundamentals": {
            "available": True,
            "metrics": computed["latest"],
            "series": computed["series"],
            "valuation": computed["valuation"],
            "red_flags": flags,
            "unavailable": computed["unavailable"],
            "currency": currency,
            "years": fetched["years"],
            "period_end": fetched["period_end"],
            "data_note": statements.describe_gaps(fetched),
            "interpretation": interpretation,
        },
        "company": crew_state.get("company") or profile.get("name") or ticker,
        "conversation_log": [state.note("fundamentals_analyst", summary)],
    }
