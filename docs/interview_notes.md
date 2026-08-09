# Interview defence notes

Plain-English answers to the questions most likely to be asked about this project.

## 1. Why can't a single LLM do this?

A single pass tends to review each source on its own and produce a fluent summary
without noticing when one source contradicts another — healthy financials sitting
next to an unexplained volatility spike, say. InvestPanel separates the research
(three specialists) from the *checking* (an analyst whose only job is to compare
specific claims across them and act on mismatches). The baseline in `eval/` exists
so this claim is measured, not asserted.

## 2. Why does the Risk agent not have its own API — where does its data come from?

It computes volatility and maximum drawdown in plain Python (`tools/volatility.py`)
from the price history the system already fetched from Alpha Vantage. A separate
"risk data" API would be a redundant dependency and cost; the math is standard and
checkable by hand.

## 3. What exactly does the Analyst's cross-check compare, mechanically?

It runs explicit detectors over the structured fields (`agents/analyst.py`), for
example: elevated annualized volatility (Risk) while every `FinancialFinding.healthy`
is true and no high-relevance risk/management `NewsFinding` exists → a real tension,
so it asks News to explain the volatility. Another compares a cheap valuation flag
against weak fundamentals plus high volatility (a value-trap pattern). Each detector
produces a `Contradiction` with one specific follow-up aimed at one specialist. An
optional LLM pass can add subtler ones, but the detectors are the backbone and are
what the tests pin down.

## 4. Why is the report disclaimer hardcoded rather than left to an agent?

So it can never be dropped or softened under prompt pressure. `Report.disclaimer` is
a frozen field, and a validator forces it back to the canonical text even if an agent
passes something else. It's enforced in code and unit-tested, not left to a prompt.

## 5. What does "confidently wrong" mean here and why is it a headline metric?

A firm conclusion that contradicts the documented reasonable read. It's called out
separately because in investing, being confidently wrong is worse than admitting
"insufficient evidence" — the first loses money, the second keeps you out of trouble.
A good system should prefer honest uncertainty over false confidence.

## 6. What is the biggest failure mode of this system?

The reasoning-quality score depends on an LLM judge, which has its own biases; and
coverage is limited to large, well-documented companies where FMP/Tavily data is
reliable. The deterministic cross-check can also miss a contradiction it has no
detector for (mitigated, not solved, by the optional LLM pass).

## 7. Why was MCP deliberately not used, and what would change if it were added?

Direct HTTP calls with httpx are simpler to build, debug, and explain for a first
project, and every external call is cached in one auditable place (`tools/cache.py`).
Adding MCP would standardize tool access and make swapping providers easier, at the
cost of another moving part to run and reason about.

## 8. What would you do next with three more months?

Wire real token-cost tracking into every run, expand the question set and re-label
it with a second reviewer, add more cross-check detectors from observed misses, run
the model-independence ablation properly, and broaden coverage beyond large caps.
