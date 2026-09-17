"""Shared LangGraph state for one financial analysis run."""

import operator
from typing import Annotated, TypedDict

from src.components import config


class CrewState(TypedDict, total=False):
    """Values passed between LangGraph nodes during one run."""

    ticker: str
    company: str
    profile: dict
    start_date: str
    end_date: str
    ticker_valid: bool

    research: dict
    fundamentals: dict
    analysis: dict
    report: str

    revision_target: str
    revision_reason: str
    revision_count: int
    max_revisions: int

    conversation_log: Annotated[list, operator.add]
    errors: Annotated[list, operator.add]


def new_state(ticker, start_date, end_date):
    """Create the initial state for a new company analysis."""
    return CrewState(
        ticker=ticker.strip().upper(),
        company="",
        profile={},
        start_date=start_date,
        end_date=end_date,
        ticker_valid=True,
        research={},
        fundamentals={},
        analysis={},
        report="",
        revision_target="",
        revision_reason="",
        revision_count=0,
        max_revisions=config.MAX_REVISIONS,
        conversation_log=[],
        errors=[],
    )
