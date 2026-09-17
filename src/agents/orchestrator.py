"""Start the crew, validate the ticker, and review the finished report."""

from pydantic import BaseModel, Field

from src import config, llm, state
from src.tools import market_data, sourcing

log = config.get_logger(__name__)


class ReviewDecision(BaseModel):
    """Structured response allowed from the LLM reviewer."""

    conflict: bool | str = Field(description="true or false")
    target: str = Field(
        default="",
        description="fundamentals_analyst, market_researcher, or empty",
    )
    reason: str = Field(default="", description="one sentence saying what to fix")


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

Set conflict to false unless the disagreement is real and specific. A report
that is merely short is not a contradiction.
"""

FLAG_KEYWORDS = {
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

VALID_REVISION_TARGETS = ("fundamentals_analyst", "market_researcher")


def run(crew_state):
    """Confirm the ticker and initialise the company name."""
    ticker = crew_state["ticker"]
    log.info("orchestrator: starting %s", ticker)

    profile = market_data.fetch_profile(ticker)
    company = profile.get("name") or ticker

    if not profile.get("currency") and not profile.get("market_cap"):
        message = (
            f"Could not confirm {ticker} on Yahoo Finance. Check the symbol. "
            "US listings need no suffix; other exchanges do, such as .L for London."
        )
        log.warning("orchestrator: %s", message)
        return {
            "company": company,
            "ticker_valid": False,
            "conversation_log": [state.note("orchestrator", message)],
            "errors": [message],
        }

    plan = (
        f"Analysing {company} ({ticker}) from {crew_state.get('start_date')} "
        f"to {crew_state.get('end_date')}. Sending the market researcher first, "
        "then the fundamentals analyst, then the data analyst."
    )
    log.info("orchestrator: %s", plan)
    return {
        "company": company,
        "ticker_valid": True,
        "conversation_log": [state.note("orchestrator", plan)],
    }


def route_after_intake(crew_state):
    """Stop early when the ticker could not be confirmed."""
    return "continue" if crew_state.get("ticker_valid", True) else "invalid_ticker"


def flags_not_mentioned(crew_state):
    """Return red flags whose subject never appears in the report."""
    report = (crew_state.get("report") or "").lower()
    if not report:
        return []

    missed = []
    for flag in crew_state.get("fundamentals", {}).get("red_flags", []):
        keyword = FLAG_KEYWORDS.get(flag["code"], "")
        if keyword and keyword not in report:
            missed.append(flag["message"])
    return missed


def review(crew_state):
    """Run deterministic checks, then use the LLM for contradiction review."""
    done = crew_state.get("revision_count", 0)
    cap = crew_state.get("max_revisions", config.MAX_REVISIONS)

    if done >= cap:
        message = f"Revision limit reached ({done} of {cap}). Accepting the report."
        log.info("orchestrator_review: %s", message)
        return {
            "revision_target": "",
            "conversation_log": [state.note("orchestrator_review", message)],
        }

    missed = flags_not_mentioned(crew_state)
    if missed:
        reason = "The report does not mention these flagged issues: " + " | ".join(missed)
        log.info(
            "orchestrator_review: sending back to fundamentals_analyst - %s",
            reason,
        )
        return {
            "revision_target": "fundamentals_analyst",
            "revision_reason": reason,
            "revision_count": done + 1,
            "conflicts": crew_state.get("conflicts", []) + missed,
            "conversation_log": [state.note("orchestrator_review", reason)],
        }

    invented = sourcing.unsourced_numbers(crew_state)
    if invented:
        reason = (
            "These numbers appear in the report but come from no calculation "
            "and no fetched article: "
            + ", ".join(invented)
            + ". Remove them or replace them with figures that were supplied."
        )
        log.info("orchestrator_review: unsourced numbers %s - sending back", invented)
        return {
            "revision_target": "fundamentals_analyst",
            "revision_reason": reason,
            "revision_count": done + 1,
            "conflicts": crew_state.get("conflicts", []) + [reason],
            "conversation_log": [state.note("orchestrator_review", reason)],
        }

    fundamentals = crew_state.get("fundamentals", {})
    research = crew_state.get("research", {})
    flags = fundamentals.get("red_flags", [])

    answer = llm.ask_structured(
        REVIEW_PROMPT.format(
            fundamentals=(fundamentals.get("interpretation") or "not available")[:1500],
            research=(research.get("summary") or "not available")[:1000],
            flags="\n".join(f"- {flag['message']}" for flag in flags) or "- none",
            report=(crew_state.get("report") or "")[:2500],
        ),
        ReviewDecision,
    )

    if answer is None:
        message = (
            "LLM contradiction review was unavailable. Deterministic checks passed, "
            "so the current report was accepted."
        )
        log.warning("orchestrator_review: %s", message)
        return {
            "revision_target": "",
            "conversation_log": [state.note("orchestrator_review", message)],
        }

    found_conflict = str(answer.conflict).strip().lower() in ("true", "yes", "1")
    if found_conflict and answer.target in VALID_REVISION_TARGETS:
        reason = answer.reason or "The reviewer found a contradiction."
        log.info(
            "orchestrator_review: sending back to %s - %s",
            answer.target,
            reason,
        )
        return {
            "revision_target": answer.target,
            "revision_reason": reason,
            "revision_count": done + 1,
            "conflicts": crew_state.get("conflicts", []) + [reason],
            "conversation_log": [
                state.note("orchestrator_review", f"{answer.target}: {reason}")
            ],
        }

    message = "No contradictions found. Report accepted."
    log.info("orchestrator_review: %s", message)
    return {
        "revision_target": "",
        "conversation_log": [state.note("orchestrator_review", message)],
    }


def route(crew_state):
    """Return the next graph route after review."""
    target = crew_state.get("revision_target", "")
    if target in VALID_REVISION_TARGETS:
        return target
    return "accept"
