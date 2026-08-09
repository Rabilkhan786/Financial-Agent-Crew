"""Track how many tokens (and roughly how much money) a run costs.

The evaluation reports cost per question, so we need to add up token usage across
every LLM call in a run. This is a small accumulator: agents call ``record`` with
the token counts from each model response, and ``summary`` gives back the totals.
Cost is a rough estimate from a per-1M-token rate kept here — good enough to
compare the baseline against the panel, which is all the eval needs.
"""

from dataclasses import dataclass, field

# Rough Gemini Flash pricing (US$ per 1,000,000 tokens). Update if the rate
# changes — it lives here so no other file hardcodes a price.
INPUT_COST_PER_MILLION = 0.10
OUTPUT_COST_PER_MILLION = 0.40


@dataclass
class UsageTracker:
    """Adds up input/output tokens and estimates the dollar cost."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    # Kept so a caller could later break usage down per agent if wanted.
    per_agent: dict[str, int] = field(default_factory=dict)

    def record(self, input_tokens: int, output_tokens: int, agent: str = "unknown") -> None:
        """Add one LLM call's token counts to the running totals."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.calls += 1
        self.per_agent[agent] = self.per_agent.get(agent, 0) + input_tokens + output_tokens

    def estimated_cost_usd(self) -> float:
        """Rough total cost of this run in US dollars."""
        return (
            self.input_tokens / 1_000_000 * INPUT_COST_PER_MILLION
            + self.output_tokens / 1_000_000 * OUTPUT_COST_PER_MILLION
        )

    def summary(self) -> dict:
        """A plain dict of the totals, handy for logging into a trace file."""
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd(), 6),
            "per_agent_tokens": self.per_agent,
        }
