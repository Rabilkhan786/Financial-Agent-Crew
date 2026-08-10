"""What the user is actually asking for, and therefore which agents need to run.

Before this existed the panel always ran Financial + News + Risk, even for a
question like "what is Nike's P/E?" — three API-heavy agents for a one-number
answer. The Query Analyzer classifies the request into an intent, and the intent
maps to a fixed set of specialists.

Why the mapping is a Python table and not something the LLM decides: routing is
control flow. If the model returns a sloppy combination we get a run that skips
the very agent the question needed. The model picks ONE label from a short list —
the cheapest, most reliable thing to ask it for — and Python derives the agent set
from that label deterministically.
"""

from typing import Literal

from pydantic import BaseModel, Field

# The kinds of request this panel can meaningfully answer differently.
QueryIntent = Literal[
    "quick_fact",             # one number or a single specific figure
    "financial_health",       # fundamentals only, no narrative needed
    "risk_only",              # volatility / downside question
    "news_only",              # what's happening lately
    "competitor_comparison",  # how does it stack up against peers
    "full_due_diligence",     # the whole checklist — the default
]

# intent -> which specialists to dispatch. Deliberately a plain table so the
# routing is auditable and unit-testable, and so a new intent can't silently
# forget to declare what it needs.
_AGENTS_FOR_INTENT: dict[str, dict[str, bool]] = {
    "quick_fact":            {"financial": True,  "news": False, "risk": False, "peers": False},
    "financial_health":      {"financial": True,  "news": False, "risk": False, "peers": False},
    "risk_only":             {"financial": False, "news": False, "risk": True,  "peers": False},
    "news_only":             {"financial": False, "news": True,  "risk": False, "peers": False},
    "competitor_comparison": {"financial": True,  "news": False, "risk": False, "peers": True},
    "full_due_diligence":    {"financial": True,  "news": True,  "risk": True,  "peers": True},
}

# When we can't tell, do the most thorough thing rather than the cheapest — a
# missing specialist silently weakens the report, which is worse than a slow run.
DEFAULT_INTENT: QueryIntent = "full_due_diligence"


class QueryPlan(BaseModel):
    """The routing decision: what was asked, and which agents that requires."""

    intent: QueryIntent = DEFAULT_INTENT
    needs_financial: bool = True
    needs_news: bool = True
    needs_risk: bool = True
    needs_peers: bool = True
    # One plain sentence, shown in the report so the user can see why some
    # sections are absent instead of assuming the panel failed.
    reasoning: str = "Defaulted to full due diligence."

    @classmethod
    def for_intent(cls, intent: str, reasoning: str = "") -> "QueryPlan":
        """Build a plan from an intent label, falling back to full due diligence."""
        if intent not in _AGENTS_FOR_INTENT:
            intent = DEFAULT_INTENT
            reasoning = reasoning or "Unrecognised intent; ran the full checklist to be safe."
        agents = _AGENTS_FOR_INTENT[intent]
        return cls(
            intent=intent,
            needs_financial=agents["financial"],
            needs_news=agents["news"],
            needs_risk=agents["risk"],
            needs_peers=agents["peers"],
            reasoning=reasoning or f"Classified as {intent.replace('_', ' ')}.",
        )

    def required_agents(self) -> list[str]:
        """The specialist node names this plan wants to run."""
        wanted = {"financial": self.needs_financial, "news": self.needs_news, "risk": self.needs_risk}
        return [name for name, needed in wanted.items() if needed]

    def skipped_agents(self) -> list[str]:
        """Specialists deliberately not run — reported, so absence is explained."""
        wanted = {"financial": self.needs_financial, "news": self.needs_news, "risk": self.needs_risk}
        return [name for name, needed in wanted.items() if not needed]


class QueryPlanRequest(BaseModel):
    """What we ask the LLM for: just the label and why. Nothing else."""

    intent: QueryIntent = DEFAULT_INTENT
    reasoning: str = Field(default="", max_length=300)
