"""What each specialist hands back — one class per specialist.

These are the contracts between the specialists and the Analyst. The most
important rule lives here: no finding may assert a fact without a source. For
financial and risk findings the source is which computation or API produced the
number; for news findings it is a real article URL, and Pydantic itself refuses
to build a NewsFinding without a valid one (``source_url`` is required). That is
the no-unsourced-facts rule enforced by the schema, not by asking the LLM nicely.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, HttpUrl

# The exact numeric metrics the checklist needs. Keeping them as a fixed list
# means the Financial agent can't invent a metric name we don't expect.
FinancialMetric = Literal[
    "revenue_growth",
    "profit_growth",
    "operating_cash_flow",
    "debt_to_equity",
    "interest_coverage",
    "roce",
    "roe",
    "pe_ratio",
    "pb_ratio",
    "valuation_vs_growth",
]


class FinancialFinding(BaseModel):
    metric: FinancialMetric
    value: float
    unit: str
    period: str
    source: str  # which API + endpoint produced this — always present
    interpretation: str  # one plain-English sentence
    healthy: bool  # the yes/no the checklist question actually needs


class NewsFinding(BaseModel):
    headline: str
    summary: str  # in your own words, never copied text
    source_url: HttpUrl  # REQUIRED — a NewsFinding cannot exist without a real URL
    published_date: date
    relevance: Literal["high", "medium", "low"]
    # Tags which judgment-call checklist question (Q7/Q8/Q9) this supports, if any.
    checklist_question: Literal["moat", "management", "risk"] | None = None


class RiskFinding(BaseModel):
    metric: str  # e.g. "annualized_volatility"
    value: float
    computed_from: str  # e.g. "252-day price history, AlphaVantage"
    interpretation: str
