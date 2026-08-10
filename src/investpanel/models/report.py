"""The final Report — the one thing the user actually sees.

Two project rules are baked into this file on purpose:

1. There is a field for every one of the 10 checklist questions, so "done" means
   all 10 are answered with evidence (or explicitly marked "insufficient
   evidence"), not "the report sounds thorough".
2. The disclaimer is hardcoded and cannot be changed or removed by any agent. A
   validator forces it back to the canonical text no matter what is passed in, and
   the field is frozen so it can't be edited after the report is built. This is why
   it's enforced in code, not left to an agent to remember under prompt pressure.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from investpanel.models.contradiction import Contradiction, Tension
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding

# The exact, required disclaimer text. Defined once, here.
DISCLAIMER_TEXT = (
    "This is informational analysis only, not investment advice. "
    "It is not a recommendation to buy, sell, or hold any security. "
    "Consult a licensed financial advisor before making investment decisions."
)


class Report(BaseModel):
    company: str
    ticker: str | None = None  # set by the Manager's scope; None if it couldn't be resolved
    company_description: str  # answers Q1, set once by the Manager
    summary: str

    # What the user typed, and how the panel read it after fixing typos/grammar.
    # Both are kept so the report can show the interpretation — if the rewrite
    # misread the question, that's visible instead of silently changing the ask.
    question: str | None = None
    interpreted_question: str | None = None

    # How the Query Analyzer routed this run. Kept so a section that is empty
    # *by design* reads as "not requested for this question" rather than the
    # misleading "insufficient evidence" (which means we tried and failed).
    query_intent: str | None = None
    routing_reason: str | None = None
    skipped_agents: list[str] = Field(default_factory=list)

    # Keys "q2".."q10": each a short answer + confidence, or "insufficient
    # evidence". This dict is what docs/evaluation.md reports completeness on.
    checklist_answers: dict[str, str] = Field(default_factory=dict)

    # metric -> {company_name: value}, for the target plus 2-3 competitors.
    peer_comparison: dict[str, dict[str, float]] = Field(default_factory=dict)

    financial_findings: list[FinancialFinding] = Field(default_factory=list)
    news_findings: list[NewsFinding] = Field(default_factory=list)
    risk_findings: list[RiskFinding] = Field(default_factory=list)
    # Closing prices behind the risk numbers, so the app can chart them. Display
    # only — every risk figure is still computed by the Risk agent, not from here.
    price_history: list[float] = Field(default_factory=list)

    contradictions_found: list[Contradiction] = Field(default_factory=list)
    contradictions_resolved: int = 0

    # Softer signals — worth a reader's attention but NOT confirmed contradictions
    # (see models/contradiction.py). Never drives the follow-up loop.
    potential_tensions: list[Tension] = Field(default_factory=list)

    # Which specialists were actually re-queried by a follow-up round, in the
    # order it happened. Lets the report say "follow-up executed" truthfully for
    # a specific contradiction instead of guessing — set by the workflow, which
    # is the only place that knows what really ran.
    followup_targets_executed: list[str] = Field(default_factory=list)

    # The date this report was generated — set automatically, not by an agent, so
    # it's always the true creation time rather than something that could be typed
    # in wrong or forgotten. Used for the "research date" data-freshness line.
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).date().isoformat())

    # frozen=True stops anyone editing it after the report is built.
    disclaimer: str = Field(default=DISCLAIMER_TEXT, frozen=True)

    @field_validator("disclaimer")
    @classmethod
    def _force_canonical_disclaimer(cls, value: str) -> str:
        # Ignore whatever was passed in and always use the canonical text. This is
        # the code-level guarantee that no agent can weaken or drop the disclaimer.
        return DISCLAIMER_TEXT
