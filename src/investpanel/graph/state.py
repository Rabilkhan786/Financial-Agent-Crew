"""The shared state that flows through the panel graph.

LangGraph passes one state object from node to node. Each specialist writes to
its own findings key, so the three can run in parallel without clashing. Two keys
(``errors`` and ``all_contradictions``) use an "add" reducer, which tells
LangGraph to *combine* values from parallel or repeated writes instead of letting
one overwrite another — needed because several nodes may append to them.
"""

import operator
from typing import Annotated, TypedDict

from investpanel.models.contradiction import Contradiction
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding
from investpanel.models.report import Report
from investpanel.models.scope import ResearchScope


class PanelState(TypedDict, total=False):
    question: str
    scope: ResearchScope | None
    company_description: str

    financial_findings: list[FinancialFinding]
    news_findings: list[NewsFinding]
    risk_findings: list[RiskFinding]
    peer_comparison: dict[str, dict[str, float]]

    # The contradictions from the most recent analyst pass.
    contradictions: list[Contradiction]
    # Every contradiction seen across all passes (add-reducer: nodes append).
    all_contradictions: Annotated[list[Contradiction], operator.add]
    # The single contradiction currently being followed up on.
    follow_up: Contradiction | None

    rounds: int  # how many follow-up rounds have run (bounded by config)
    report: Report | None
    # Problems that didn't stop the run (add-reducer: nodes append).
    errors: Annotated[list[str], operator.add]
    # Which specialists were actually re-queried by a follow-up round, in order
    # (add-reducer: the specialist node itself appends when it runs as a
    # follow-up). This is how the report can honestly say "follow-up executed"
    # for a specific contradiction instead of guessing after the fact.
    resolved_targets: Annotated[list[str], operator.add]
