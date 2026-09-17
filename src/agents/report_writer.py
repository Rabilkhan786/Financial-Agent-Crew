"""Write the final report from the completed agent findings."""

from src.components.logging import get_logger
from src.core import llm
from src.utils import formatting

log = get_logger(__name__)

PROMPT = """Write a concise financial analysis report.

Company: {company} ({ticker})
Period: {start} to {end}

Fundamentals analysis:
{fundamentals}

Market research:
{research}

Price analysis:
{analysis}

Calculated fundamental metrics:
{fundamental_facts}

Calculated price metrics:
{price_facts}

Red flags:
{flags}

Use exactly these headings:
## Executive summary
## Growth
## Profitability
## Cash generation
## Balance sheet
## Valuation
## Market context
## Recommendation

Use only the supplied evidence and numbers. Do not invent values.
Under Recommendation, summarize positives, risks, and what evidence could change the assessment.
Do not tell the reader to buy, sell, or hold the stock.
"""

DISCLAIMER = (
    "This report is generated from public data for educational purposes only. "
    "It is not investment advice."
)


def run(crew_state):
    """Combine agent outputs into one final report."""
    ticker = crew_state["ticker"]
    fundamentals = crew_state.get("fundamentals") or {}
    research = crew_state.get("research") or {}
    analysis = crew_state.get("analysis") or {}

    fundamental_facts = formatting.facts_block(
        fundamentals.get("metrics") or {},
        fundamentals.get("currency"),
    )
    price_facts = formatting.facts_block(analysis.get("kpis") or {})

    flags = fundamentals.get("red_flags") or []
    flag_text = "\n".join(
        f"- [{flag['severity']}] {flag['message']}"
        for flag in flags
    ) or "- none"

    body = llm.ask(
        PROMPT.format(
            company=crew_state.get("company") or ticker,
            ticker=ticker,
            start=crew_state.get("start_date"),
            end=crew_state.get("end_date"),
            fundamentals=fundamentals.get("interpretation") or "not available",
            research=research.get("summary") or "not available",
            analysis=analysis.get("interpretation") or "not available",
            fundamental_facts=fundamental_facts or "- unavailable",
            price_facts=price_facts or "- unavailable",
            flags=flag_text,
        )
    )

    if not body:
        body = "## Executive summary\n\nThe language model did not return a report."

    report = (
        f"# {crew_state.get('company') or ticker} ({ticker})\n\n"
        f"{body}\n\n"
        "## Red flags\n"
        f"{flag_text}\n\n"
        "## Data notes\n"
        f"{fundamentals.get('data_note') or 'No additional data notes.'}\n\n"
        f"---\n{DISCLAIMER}"
    )

    message = f"Wrote the final report ({len(report)} characters)."
    log.info("%s: %s", ticker, message)

    return {
        "report": report,
        "conversation_log": [
            {"agent": "report_writer", "message": message}
        ],
    }
