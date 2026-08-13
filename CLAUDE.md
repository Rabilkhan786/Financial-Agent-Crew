# CLAUDE.md — Financial Analysis Agent Crew

Loaded automatically at the start of every session. Read it fully before acting.

## What this is

A multi-agent fundamental-analysis system. The user enters a stock ticker and a date
range in Streamlit; a LangGraph agent crew produces a fundamental analysis report,
shown in-app and exported as PDF.

This repo previously held a different project (InvestPanel). It was deleted and
replaced on 2026-08-13. The old code is recoverable at the git tag `pre-crew-rewrite`.

**This produces informational analysis, not investment advice.**

## Graph

```
START -> orchestrator -> market_researcher -> fundamentals_analyst
      -> data_analyst -> report_writer -> orchestrator_review
      |-> fundamentals_analyst (revise)
      |-> market_researcher   (revise)
      |-> END
```

`orchestrator_review` is a conditional edge returning one of three strings. The revise
loop is capped: the review node checks `revision_count >= max_revisions` at the top and
force-accepts. `graph.invoke` is called with `recursion_limit=25`.

## Non-negotiable rules

1. `src/tools/ratios.py` and `src/tools/kpi.py` are pure pandas/numpy — no LLM import,
   no network. Every function unit tested. **The LLM never does arithmetic**; it only
   interprets numbers it is handed.
2. `src/agents/report_writer.py` imports nothing from `src/tools/`. It reads state and writes.
3. Red flags are deterministic rules in `ratios.py`, not LLM opinion.
4. Reddit (`src/tools/social.py`) is optional. Missing keys -> the app still runs. Fewer
   than 5 posts -> `social_sentiment = "insufficient data"`, set before the LLM sees anything.
5. Missing statement data (common for Indian smallcaps) is reported as unavailable,
   never inferred by the LLM.
6. `src/cache.py` from the start — disk cache keyed by ticker+date for yfinance, news, Reddit.
7. fpdf2: sanitise every string to latin-1, and call `set_x(l_margin)` before each `multi_cell`.
8. LangSmith: read `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` from `.env`.
   Pass `config={"run_name": f"crew-{ticker}", "tags": [ticker], "recursion_limit": 25}`
   to `graph.invoke`. A missing LangSmith key must never break a run.
9. Do not add agents, data sources, RAG, or price prediction beyond what is listed here.

## Structure

```
app.py  requirements.txt  Dockerfile  .dockerignore  .env.example  .gitignore  README.md
src/{state,llm,graph,charts,report_pdf,cache}.py
src/agents/{orchestrator,market_researcher,fundamentals_analyst,data_analyst,report_writer}.py
src/tools/{market_data,statements,ratios,kpi,news,social}.py
tests/{test_ratios,test_kpi}.py
evals/run_eval.py
output/   (gitignored)
```

## Environment — uv

uv manages the environment at `.venv/` (Python 3.11). Dependencies are listed in
`requirements.txt`; uv installs them. There is no pyproject.toml by design.

```
uv pip install -r requirements.txt      # VIRTUAL_ENV=.venv must be set, or run from repo root
uv run --no-project python -m pytest
uv run --no-project streamlit run app.py
```

Docker uses the same `requirements.txt` via uv, so container and laptop match.

## Build order — stop and confirm after each step

1. [x] Delete old files, set up folder structure  (+ Dockerfile, uv env, deps installed)
2. [ ] `tools/ratios.py` + `tests/test_ratios.py` — tests passing
3. [ ] `tools/kpi.py` + `tests/test_kpi.py` — tests passing
4. [ ] `tools/statements.py`, `tools/market_data.py`, `cache.py`
5. [ ] `state.py`, `llm.py`
6. [ ] `fundamentals_analyst` standalone — confirm output before wiring the graph
7. [ ] remaining four agents
8. [ ] `graph.py`
9. [ ] `charts.py`, `report_pdf.py`
10. [ ] `app.py`
11. [ ] `evals/run_eval.py` — 10 tickers, three rule checks
12. [ ] README — design decisions, why LangGraph, why the loop is capped, why KPIs are in Python

## Code style

The person maintaining this code is early-career and must be able to explain every line
in an interview. Plain, explicit code over clever abstractions. Short functions that do
one obvious thing. Type hints and tests stay. Comment the "why" wherever the code enforces
a rule above (the loop cap, the no-LLM-arithmetic boundary, the disclaimer).

Explain each file to the user in 2-4 sentences of plain English as it is created.

## Keys

`.env` holds real keys and is gitignored. `.env.example` is committed and must never
contain a real key. Required: `GOOGLE_API_KEY`. Optional: LangSmith and Reddit keys.
