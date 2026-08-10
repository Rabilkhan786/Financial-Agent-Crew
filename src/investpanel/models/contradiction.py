"""A contradiction the Analyst found between two specialists' findings.

This model is the visible output of the whole point of the project: the Analyst
does not just merge the three reports, it looks for places where the numeric story
and the qualitative story disagree (e.g. "margins improved" from Financial vs
"restructuring announced last month" from News). When it finds one, it records it
here and aims a single, specific follow-up question at exactly one specialist.
"""

from typing import Literal

from pydantic import BaseModel

Specialist = Literal["financial", "news", "risk"]


class Contradiction(BaseModel):
    # Which two specialists disagree, e.g. ("financial", "news").
    between: tuple[Specialist, Specialist]
    description: str  # plain-English explanation of the tension
    follow_up_target: Specialist  # the ONE specialist to re-ask
    follow_up_question: str  # a specific question, not "please recheck"


class Tension(BaseModel):
    """A softer signal than a Contradiction: two findings worth a reader's attention
    (e.g. revenue up while profit is down) that are NOT automatically a genuine
    disagreement. Tensions never drive the follow-up loop — they exist purely so
    the report can be honest about "this deserves a second look" without
    over-claiming a contradiction that isn't really there.
    """

    between: tuple[Specialist, Specialist]
    description: str  # the two facts in tension, plainly stated
    reason: str  # why this is a tension worth noting, not a confirmed conflict
