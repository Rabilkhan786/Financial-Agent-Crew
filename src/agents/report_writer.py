"""Writes the final report.

This file imports nothing from tools/. It only reads what the other agents put
in the state. That keeps one clear rule: by the time we get here, every number
has already been worked out and checked, and writing cannot quietly change it.
"""

from src import config, formatting, llm, state

log = config.get_logger(__name__)

# Always printed, word for word. Not something an agent decides to include.
DISCLAIMER = (
    "This report is informational analysis produced automatically from public "
    "data. It is not investment advice, and it is not a recommendation to buy "
    "or sell any security. Figures come from Yahoo Finance and may contain "
    "errors. Always do your own research and speak to a licensed adviser "
    "before investing."
)

PROMPT = """You are writing a fundamental analysis report for a private investor.

Company: {company} ({ticker})
Period reviewed: {start} to {end}
Reporting currency: {currency}

WHAT THE FUNDAMENTALS ANALYST FOUND
{fundamentals}

WHAT THE MARKET RESEARCHER FOUND
{research}

WHAT THE DATA ANALYST FOUND
{analysis}

THE NUMBERS (already calculated - use exactly these)
{facts}

PRICE NUMBERS (already calculated - use exactly these)
{price_facts}

AUTOMATED RED FLAGS
{flags}

DATA GAPS
{gaps}

{conflicts}

Write the report with exactly these headings, in this order:

## Executive summary
## Business quality
## Growth
## Profitability
## Cash generation
## Balance sheet
## Valuation
## Market context
## Recommendation

Rules:
- Use only the numbers given above. Never invent, round differently, or
  estimate a figure. If a number is not listed, do not state one.
- Anything listed as a data gap must be described as unavailable.
- Every red flag must appear in the report. Do not soften or skip one.
- Under Recommendation, give a view (for example: worth a closer look, wait,
  avoid for now) and say plainly what would change your mind. Do not give
  price targets and do not tell the reader to buy or sell.
- Short paragraphs. Plain English. No jargon without a short explanation.
"""


def facts_from(crew_state):
    """The calculated fundamentals, as text the model can quote."""
    fundamentals = crew_state.get("fundamentals", {})
    if not fundamentals.get("available"):
        return "No statement data was available for this company."
    return formatting.facts_block(fundamentals.get("metrics", {}),
                                  fundamentals.get("currency"))


def price_facts_from(crew_state):
    """The calculated price numbers, as text the model can quote."""
    analysis = crew_state.get("analysis", {})
    if not analysis.get("available"):
        return "No price data was available for this company."

    lines = [formatting.facts_block(analysis.get("kpis", {}))]
    lines.append(f"- Trend: {analysis.get('trend')}")
    against_index = analysis.get("benchmark")
    if against_index:
        lines.append(f"- Against {analysis.get('benchmark_symbol')}: "
                     f"{against_index['verdict']}")
    return "\n".join(lines)


def flags_from(crew_state):
    """The red flags, exactly as the rules wrote them."""
    fundamentals = crew_state.get("fundamentals", {})
    flags = fundamentals.get("red_flags", [])
    if not flags:
        return "None. No automated check was triggered."
    return "\n".join(f"- [{flag['severity']}] {flag['message']}" for flag in flags)


def gaps_from(crew_state):
    """What could not be calculated, so the report can say so."""
    fundamentals = crew_state.get("fundamentals", {})
    parts = []
    if fundamentals.get("data_note"):
        parts.append(fundamentals["data_note"])
    if fundamentals.get("unavailable"):
        parts.append("Ratios that could not be calculated: "
                     + ", ".join(fundamentals["unavailable"]))
    analysis = crew_state.get("analysis", {})
    if analysis.get("unavailable"):
        parts.append("Price measures that could not be calculated: "
                     + ", ".join(analysis["unavailable"]))
    research = crew_state.get("research", {})
    if research.get("social_sentiment") == "insufficient data":
        parts.append("Retail chatter: insufficient data (too few posts to judge).")
    return "\n".join(parts) or "None."


def run(crew_state):
    """Write the report from what is already in the state."""
    ticker = crew_state["ticker"]
    log.info("report_writer: starting %s", ticker)

    fundamentals = crew_state.get("fundamentals", {})
    research = crew_state.get("research", {})
    analysis = crew_state.get("analysis", {})

    conflicts = ""
    if crew_state.get("conflicts"):
        conflicts = ("THE REVIEWER RAISED THESE POINTS - you must address each one:\n"
                     + "\n".join(f"- {item}" for item in crew_state["conflicts"]))

    body = llm.ask(PROMPT.format(
        company=crew_state.get("company") or ticker,
        ticker=ticker,
        start=crew_state.get("start_date"),
        end=crew_state.get("end_date"),
        currency=fundamentals.get("currency") or "unknown",
        fundamentals=fundamentals.get("interpretation") or "not available",
        research=research.get("summary") or "not available",
        analysis=analysis.get("interpretation") or "not available",
        facts=facts_from(crew_state),
        price_facts=price_facts_from(crew_state),
        flags=flags_from(crew_state),
        gaps=gaps_from(crew_state),
        conflicts=conflicts,
    ))

    if not body:
        body = ("## Executive summary\n\nThe report could not be written because the "
                "language model did not respond. The calculated figures below are "
                "still correct and can be read directly.")

    # The red flags and the disclaimer are added here as fixed text rather than
    # left to the model, so they can never be dropped or reworded.
    report = "\n".join([
        f"# {crew_state.get('company') or ticker} ({ticker})",
        f"Fundamental analysis - {crew_state.get('start_date')} to "
        f"{crew_state.get('end_date')}",
        "",
        body,
        "",
        "## Red flags",
        flags_from(crew_state),
        "",
        "## Data notes",
        gaps_from(crew_state),
        "",
        "---",
        DISCLAIMER,
    ])

    log.info("report_writer: wrote %d characters", len(report))
    return {
        "report": report,
        "conversation_log": [state.note("report_writer",
                                        f"Wrote the report ({len(report)} characters).")],
    }
