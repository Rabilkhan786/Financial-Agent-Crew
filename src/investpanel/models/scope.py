"""The research scope — what the Manager decides before anyone starts work.

Rule for the whole project: agents only ever hand each other Pydantic models,
never free-form text. This is the first one. The Manager reads the question and
fills this in: which company, its ticker, 2-3 real competitors (found by a real
search, never guessed), the time window, and any focus the question implies.
"""

from pydantic import BaseModel, Field


class ResearchScope(BaseModel):
    company: str
    ticker: str | None = None
    # 2-3 real competitors found via search, so numbers can be compared to peers.
    competitors: list[str] = Field(default_factory=list)
    time_window: str = "last 12 months"
    # Set only if the question points at something specific (e.g. "debt levels").
    priority_focus: str | None = None
