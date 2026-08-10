"""Critic — challenges the specialists before the Analyst is allowed to conclude.

Runs after Financial, News and Risk finish and before the Analyst writes anything.
Its whole job is to look for places where the three disagree — "strong cash
generation" next to rising debt, healthy numbers next to a serious news story — and
to state those tensions out loud.

Why it is a separate agent rather than a step inside the Analyst: the Analyst's job
is to synthesize, and synthesis has a natural pull toward a tidy story. Splitting the
challenge into its own node means the contradictions are recorded as their own
output, and the Analyst receives them as input it must address rather than something
it can quietly smooth over.

The detectors themselves stay deterministic (agents/analyst.py holds the pure
functions, unchanged and unit-tested); the Critic orchestrates them, adds the
optional LLM pass, and separates confirmed contradictions from softer tensions.
"""

from investpanel.agents.analyst import detect_contradictions, detect_potential_tensions
from investpanel.agents.base import BaseAgent
from investpanel.models.contradiction import Contradiction, Tension
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding
from investpanel.utils.logging import get_logger

logger = get_logger(__name__)


class CriticAgent(BaseAgent):
    """Cross-examines the specialists' findings and reports what doesn't line up."""

    name = "critic"

    def review(
        self,
        financial: list[FinancialFinding],
        news: list[NewsFinding],
        risk: list[RiskFinding],
        peer_comparison: dict[str, dict[str, float]] | None = None,
        target_ticker: str | None = None,
    ) -> tuple[list[Contradiction], list[Tension]]:
        """Return (confirmed contradictions, potential tensions).

        The two are kept apart on purpose: a contradiction is a genuine
        disagreement that earns a follow-up round, while a tension is only worth
        a reader's attention. Collapsing them would either spam the follow-up loop
        or bury real conflicts.
        """
        contradictions = detect_contradictions(
            financial, news, risk, peer_comparison, target_ticker
        )
        tensions = detect_potential_tensions(financial, news, risk)

        logger.info(
            "Critic: %d contradiction(s), %d tension(s)", len(contradictions), len(tensions)
        )
        self.trace({
            "num_contradictions": len(contradictions),
            "num_tensions": len(tensions),
            "contradictions": [c.model_dump(mode="json") for c in contradictions],
            "tensions": [t.model_dump(mode="json") for t in tensions],
        })
        return contradictions, tensions
