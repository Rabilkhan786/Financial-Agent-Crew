"""Validate the ticker and review the final report."""

from pydantic import BaseModel, Field

from src.components.logging import get_logger
from src.core import llm
from src.tools import market_data

log = get_logger(__name__)


class ReviewDecision(BaseModel):
    """Small structured response used by the reviewer."""

    needs_revision: bool = False
    target: str = Field(default="")
    reason: str = Field(default="")


REVIEW_PROMPT = """Review this financial report against the agent findings.

Fundamentals:
{fundamentals}

Market research:
{research}

Red flags:
{flags}

Report:
{report}

Decide whether the report has a clear contradiction or misses an important risk.
If revision is needed, target only one of:
- fundamentals_analyst
- market_researcher

Do not request a revision only because the writing could be better.
"""

VALID_TARGETS = {"fundamentals_analyst", "market_researcher"}


def run(crew_state):
    """Validate the ticker before starting the workflow."""
    ticker = crew_state["ticker"]
    profile = market_data.fetch_profile(ticker)
    company = profile.get("name") or ticker

    valid = bool(profile.get("currency") or profile.get("market_cap"))
    if not valid:
        message = f"Could not validate ticker {ticker}."
        return {
            "company": company,
            "ticker_valid": False,
            "conversation_log": [
                {"agent": "orchestrator", "message": message}
            ],
            "errors": [message],
        }

    message = f"Validated {company} ({ticker}) and started the analysis."
    return {
        "company": company,
        "ticker_valid": True,
        "conversation_log": [
            {"agent": "orchestrator", "message": message}
        ],
    }


def route_after_intake(crew_state):
    """Stop when the ticker is invalid."""
    return "continue" if crew_state.get("ticker_valid") else "stop"


def review(crew_state):
    """Review the report and optionally send one agent back to revise."""
    revision_count = crew_state.get("revision_count", 0)
    max_revisions = crew_state.get("max_revisions", 1)

    if revision_count >= max_revisions:
        return {
            "revision_target": "",
            "conversation_log": [
                {
                    "agent": "orchestrator_review",
                    "message": "Revision limit reached. Report accepted.",
                }
            ],
        }

    fundamentals = crew_state.get("fundamentals") or {}
    research = crew_state.get("research") or {}
    flags = fundamentals.get("red_flags") or []

    decision = llm.ask_structured(
        REVIEW_PROMPT.format(
            fundamentals=(fundamentals.get("interpretation") or "not available")[:1500],
            research=(research.get("summary") or "not available")[:1200],
            flags="\n".join(f"- {item['message']}" for item in flags) or "- none",
            report=(crew_state.get("report") or "")[:2500],
        ),
        ReviewDecision,
    )

    if decision and decision.needs_revision and decision.target in VALID_TARGETS:
        reason = decision.reason or "Reviewer requested a correction."
        return {
            "revision_target": decision.target,
            "revision_reason": reason,
            "revision_count": revision_count + 1,
            "conversation_log": [
                {
                    "agent": "orchestrator_review",
                    "message": f"Sending back to {decision.target}: {reason}",
                }
            ],
        }

    return {
        "revision_target": "",
        "conversation_log": [
            {
                "agent": "orchestrator_review",
                "message": "Review passed. Report accepted.",
            }
        ],
    }


def route_after_review(crew_state):
    """Return the next LangGraph route after review."""
    target = crew_state.get("revision_target", "")
    return target if target in VALID_TARGETS else "accept"
