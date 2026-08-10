"""A financially material finding that falls OUTSIDE the fixed checklist.

The 10-question checklist is the minimum every report must cover, not the limit of
what the panel may notice. A company can be perfectly healthy on all ten and still
have something a reader needs to know — an operating margin that collapsed, cash
flow that stopped backing profit, a valuation priced for growth that isn't there.

Same rule as every other finding: an Observation must cite the evidence it came
from, so nothing here is an unsourced opinion.
"""

from typing import Literal

from pydantic import BaseModel

# Where the observation came from, so the report can group them.
ObservationSource = Literal["financial", "risk", "news"]

# How much it should worry a reader. Deliberately not a score — a made-up number
# would imply precision this doesn't have.
Severity = Literal["info", "watch", "concern"]


class Observation(BaseModel):
    """Something materially relevant that no checklist question asked about."""

    source: ObservationSource
    title: str  # a short label, e.g. "Operating margin nearly halved"
    detail: str  # one or two plain sentences explaining what was seen
    severity: Severity = "info"
    # The concrete numbers/metrics behind it — an observation with no evidence
    # is an opinion, and this project doesn't publish those.
    evidence: list[str] = []
