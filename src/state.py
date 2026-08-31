"""This is the shared data every agent reads and writes.

One agent adds its part, then passes it to the next agent.
"""

import operator
from typing import Annotated, TypedDict

from src import config


class CrewState(TypedDict, total=False):
    """Everything the crew knows about one company."""

    # What was asked for
    ticker: str
    company: str
    start_date: str
    end_date: str
    ticker_valid: bool      # set by orchestrator.run(); gates whether the crew continues

    # What each agent produced
    research: dict          # market_researcher: news, social posts, market context
    fundamentals: dict      # fundamentals_analyst: the ratios and what they mean
    analysis: dict          # data_analyst: price KPIs and charts
    report: str             # report_writer: the finished text

    # The revise loop
    revision_target: str    # which agent to send it back to, or "" for none
    revision_reason: str    # what the orchestrator wants fixed
    revision_count: int     # how many revisions have happened so far
    max_revisions: int      # the cap, so the loop cannot run forever
    conflicts: list         # disagreements the orchestrator spotted

    # These two grow as the run goes on. `operator.add` tells LangGraph to join
    # the lists together instead of letting one agent overwrite another's.
    conversation_log: Annotated[list, operator.add]
    errors: Annotated[list, operator.add]


def new_state(ticker, start_date, end_date):
    """A fresh state at the start of a run."""
    return CrewState(
        ticker=ticker.strip().upper(),
        company="",
        start_date=start_date,
        end_date=end_date,
        ticker_valid=True,      # optimistic; orchestrator.run() sets this False if it fails
        research={},
        fundamentals={},
        analysis={},
        report="",
        revision_target="",
        revision_reason="",
        revision_count=0,
        max_revisions=config.MAX_REVISIONS,
        conflicts=[],
        conversation_log=[],
        errors=[],
    )


def note(agent, message):
    """One entry for the conversation log.

    The log is shown in the app and printed as an appendix in the PDF, so the
    reader can see what each agent said and why the report came out as it did.
    """
    return {"agent": agent, "message": message}
