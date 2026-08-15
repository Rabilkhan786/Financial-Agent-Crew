"""Runs the crew: sets the job up at the start, and reviews the report at the end.

The review is the interesting part. It looks for places where the fundamentals
and the market research do not agree, and sends the report back to whichever
agent can fix it. The loop is capped so two agents cannot argue forever.
"""

from src import config, llm, state
from src.tools import market_data

log = config.get_logger(__name__)

REVIEW_PROMPT = """You are reviewing a draft investment report for contradictions.

WHAT THE FUNDAMENTALS SAY
{fundamentals}

WHAT THE MARKET RESEARCH SAYS
{research}

AUTOMATED RED FLAGS
{flags}

THE DRAFT REPORT
{report}

Look for a real contradiction between these, for example: the fundamentals show
falling margins but the research describes only good news, or a red flag was
raised but the report does not mention it.

Reply with JSON only:
{{"conflict": true or false,
  "target": "fundamentals_analyst" or "market_researcher" or "",
  "reason": "one sentence saying exactly what to fix"}}

Set conflict to false unless the disagreement is real and specific. A report
that is merely short is not a contradiction.
"""


def run(crew_state):
    """Set the job up: confirm the ticker is real and name the company."""
    ticker = crew_state["ticker"]
    log.info("orchestrator: starting %s", ticker)

    profile = market_data.fetch_profile(ticker)
    company = profile.get("name") or ticker

    if not profile.get("currency") and not profile.get("market_cap"):
        message = (f"Could not confirm {ticker} on Yahoo Finance. "
                   "Check the symbol. US listings need no suffix; other "
                   "exchanges do, such as .L for London.")
        log.warning("orchestrator: %s", message)
        return {"company": company,
                "conversation_log": [state.note("orchestrator", message)],
                "errors": [message]}

    plan = (f"Analysing {company} ({ticker}) from {crew_state.get('start_date')} "
            f"to {crew_state.get('end_date')}. Sending the market researcher first, "
            "then the fundamentals analyst, then the data analyst.")
    log.info("orchestrator: %s", plan)
    return {"company": company,
            "conversation_log": [state.note("orchestrator", plan)]}


def flags_not_mentioned(crew_state):
    """Red flags whose subject never appears in the report.

    A plain word check, done in Python. If a rule fired and the report does not
    talk about it, the report is hiding something.
    """
    report = (crew_state.get("report") or "").lower()
    if not report:
        return []

    # The word to look for in the report, per flag.
    keywords = {
        "weak_cash_conversion": "cash",
        "negative_operating_cash_flow": "cash",
        "persistent_negative_fcf": "cash",
        "negative_equity": "equity",
        "high_leverage": "debt",
        "thin_interest_cover": "interest",
        "margin_erosion": "margin",
        "earnings_quality": "cash",
        "revenue_decline": "revenue",
    }

    missed = []
    for flag in crew_state.get("fundamentals", {}).get("red_flags", []):
        word = keywords.get(flag["code"], "")
        if word and word not in report:
            missed.append(flag["message"])
    return missed


def review(crew_state):
    """Check the draft, and decide whether to send it back.

    The cap is checked first, before anything else. Once the limit is reached
    the report is accepted as it stands, whatever the review would have said.
    """
    done = crew_state.get("revision_count", 0)
    cap = crew_state.get("max_revisions", config.MAX_REVISIONS)

    if done >= cap:
        message = f"Revision limit reached ({done} of {cap}). Accepting the report."
        log.info("orchestrator_review: %s", message)
        return {"revision_target": "",
                "conversation_log": [state.note("orchestrator_review", message)]}

    # A cheap, certain check first: did the report drop a red flag?
    missed = flags_not_mentioned(crew_state)
    if missed:
        reason = ("The report does not mention these flagged issues: "
                  + " | ".join(missed))
        log.info("orchestrator_review: sending back to fundamentals_analyst - %s", reason)
        return {
            "revision_target": "fundamentals_analyst",
            "revision_reason": reason,
            "revision_count": done + 1,
            "conflicts": crew_state.get("conflicts", []) + missed,
            "conversation_log": [state.note("orchestrator_review", reason)],
        }

    fundamentals = crew_state.get("fundamentals", {})
    research = crew_state.get("research", {})
    flags = fundamentals.get("red_flags", [])

    answer = llm.ask_json(REVIEW_PROMPT.format(
        fundamentals=fundamentals.get("interpretation") or "not available",
        research=research.get("summary") or "not available",
        flags="\n".join(f"- {flag['message']}" for flag in flags) or "- none",
        report=(crew_state.get("report") or "")[:6000],
    ))

    target = answer.get("target", "")
    valid = ("fundamentals_analyst", "market_researcher")
    if answer.get("conflict") and target in valid:
        reason = answer.get("reason", "The reviewer found a contradiction.")
        log.info("orchestrator_review: sending back to %s - %s", target, reason)
        return {
            "revision_target": target,
            "revision_reason": reason,
            "revision_count": done + 1,
            "conflicts": crew_state.get("conflicts", []) + [reason],
            "conversation_log": [state.note("orchestrator_review", f"{target}: {reason}")],
        }

    message = "No contradictions found. Report accepted."
    log.info("orchestrator_review: %s", message)
    return {"revision_target": "",
            "conversation_log": [state.note("orchestrator_review", message)]}


def route(crew_state):
    """Where to go after the review. One of exactly three answers."""
    target = crew_state.get("revision_target", "")
    if target == "fundamentals_analyst":
        return "fundamentals_analyst"
    if target == "market_researcher":
        return "market_researcher"
    return "accept"
