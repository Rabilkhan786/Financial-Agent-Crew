"""The shared state that every agent reads from and writes to.

LangGraph passes one dictionary through the whole graph. Each agent adds its
own part and leaves the rest alone. Keeping it in one TypedDict means there is
a single list of everything the crew knows about a company.
"""

from __future__ import annotations

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


def new_state(ticker: str, start_date: str, end_date: str) -> CrewState:
    """A fresh state at the start of a run."""
    return CrewState(
        ticker=ticker.strip().upper(),
        company="",
        start_date=start_date,
        end_date=end_date,
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


def note(agent: str, message: str) -> dict:
    """One entry for the conversation log.

    The log is shown in the app and printed as an appendix in the PDF, so the
    reader can see what each agent said and why the report came out as it did.
    """
    return {"agent": agent, "message": message}
