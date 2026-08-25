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
3b. Every number in the report must trace to a calculation or a fetched headline.
   `src/tools/sourcing.py` is the one implementation; `orchestrator.review` sends a
   report back when it finds one that does not, and `evals/run_eval.py` imports the
   same function so the eval tests the real guard.
4. Social sentiment (`src/tools/social.py`) is optional. Missing keys -> the app still
   runs. Fewer than 5 posts -> `social_sentiment = "insufficient data"`, set before the
   LLM sees anything.
   **Two backends behind one function** (user decision, 2026-08-13): praw/Reddit when
   `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are set, otherwise keyless StockTwits.
   Reddit commercial API approval takes weeks; keyless Reddit JSON is 403 everywhere,
   verified. StockTwits returns 200 with no key and its posts carry self-declared
   Bullish/Bearish tags, so sentiment is counted rather than inferred. Either backend
   failing degrades to "insufficient data" — it never breaks a run.
5. Missing statement data is reported as unavailable, never inferred by the LLM.
6. `src/cache.py` from the start — disk cache keyed by ticker+date for yfinance, news, Reddit.
7. fpdf2: sanitise every string to latin-1, and call `set_x(l_margin)` before each `multi_cell`.
8. LangSmith: read `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` from `.env`.
   Pass `config={"run_name": f"crew-{ticker}", "tags": [ticker], "recursion_limit": 25}`
   to `graph.invoke`. A missing LangSmith key must never break a run.
9. Do not add agents, data sources, RAG, or price prediction beyond what is listed here.

## Structure

```
app.py  requirements.txt  Dockerfile  .dockerignore  .env.example  .gitignore  README.md
src/{config,state,llm,graph,charts,report_pdf,cache}.py
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
2. [x] `tools/ratios.py` + `tests/test_ratios.py` — tests passing
3. [x] `tools/kpi.py` + `tests/test_kpi.py` — tests passing
4. [x] `tools/statements.py`, `tools/market_data.py`, `cache.py`, `news.py`, `social.py`,
       plus `config.py` and logging (verified live on AAPL and BA)
5. [x] `state.py`, `llm.py`
6. [x] `fundamentals_analyst` standalone — confirm output before wiring the graph
7. [x] remaining four agents
8. [x] `graph.py`
9. [x] `charts.py`, `report_pdf.py`
10. [x] `app.py`
11. [x] `evals/run_eval.py` — 10 US tickers, three rule checks
12. [x] README — design decisions, why LangGraph, why the loop is capped, why KPIs are in Python

## Code style

The person maintaining this code is at the 0-1 year mark and must be able to explain
every line in an interview. Write it the way they would: plain, short, obvious.
No clever abstractions, no metaprogramming, no deep class hierarchies, no one-liners
that need a second read. If there is a simple way and a "proper enterprise" way, use
the simple way. Plain, explicit code over clever abstractions. Short functions that do
one obvious thing. Type hints and tests stay. Comment the "why" wherever the code enforces
a rule above (the loop cap, the no-LLM-arithmetic boundary, the disclaimer).

Explain each file to the user in 2-4 sentences of plain English as it is created.

## What was learned live (do not re-discover)

* **Gemini 2.5 models are blocked for this key** — `gemini-2.5-flash` returns 404
  "no longer available to new users". Working models: `gemini-3.5-flash` (default,
  ~1.5s), `gemini-3.6-flash`, `gemini-3.1-flash-lite`, `gemini-flash-latest`.
  3.6 ignores the temperature setting; 3.5 respects it, which is why 3.5 is default.
* **Gemini returns `message.content` as a LIST of blocks, not a string.** `llm.py`
  must normalise it to text, or every downstream `.strip()` breaks.
* **Finnhub free plans 403 on non-US tickers** — `news.py` catches that and falls
  back to Yahoo. Do not "fix" the fallback by only checking for an empty list.
* **StockTwits 404/403s on non-US tickers** — expected; yields "insufficient data".
* **Yahoo row labels are consistent across exchanges** ("Total Revenue",
  "Stockholders Equity", "Capital Expenditure"), so one `FIELD_MAP` in statements.py
  covers them all. A typical US listing gives 12 of 12 fields across 5 years.

## Model provider

Groq only, through LangChain. `GROQ_MODEL` in `.env`, default `openai/gpt-oss-120b`.
Gemini and Ollama support was removed once Groq settled: dead code that had to be
kept working for no benefit.

* **Which models a key can reach varies by account.** A second key had 13 models and
  no llama, so `llama-3.3-70b-versatile` 404ed everywhere. List the models for the key
  in hand rather than trusting a name that worked before.
* Free tier limits **tokens per minute** (8000). `llm.get_llm()` uses LangChain
  `.with_retry(stop_after_attempt=5, wait_exponential_jitter=True)` for that.
* `groq/compound` has 70000 TPM but runs its own web searches. Not used: it would
  feed the writer numbers the sourcing guard never saw.

## Known limit

Gemini free tier allows **20 requests per day per model**. One crew run uses about
five. A ten-company eval therefore cannot finish in one day on one model: run it in
batches, switch `GEMINI_MODEL` (each model has its own quota), or use a paid key.
When the quota runs out the report writer gets no reply and produces a short stub.

## Logging

`config.get_logger(__name__)` in every module. Console plus `output/run.log`.
Every fetch, cache hit, fallback and skipped agent is logged — during a multi-agent
run the log is the only way to see who asked for what, in which order.

## Keys

`.env` holds real keys and is gitignored. `.env.example` is committed and must never
contain a real key. Required: `GOOGLE_API_KEY`. Optional: LangSmith and Reddit keys.

## Portfolio scope (user decision, 2026-08-15)

**US companies only.** The eval roster is ten US listings: AAPL, MSFT, JNJ, KO, PG
(healthy) and F, T, INTC, BA, WBA (chosen to set off red flags - Boeing has negative
equity, Ford and AT&T are heavily borrowed, Intel burns cash, Walgreens is shrinking).

The `.NS`/`.BO`/`.L` benchmark routing in `kpi.py` stays and is still unit tested: it
is correct code and removing it would weaken the "beat the right index" argument. Just
do not use Indian tickers in demos, the README or the eval.

## Framework over hand-written code (2026-08-25)

Following *Generative AI with LangChain* (Auffarth & Kuligin):

* **Structured output** (`llm.ask_structured` + a pydantic model) replaced the
  hand-written `ask_json`, code-fence stripping and reparse loop. The reviewer's
  answer is now a `ReviewDecision` object, ch.5.
* **`graph.stream(stream_mode="values")`** (ch.6) replaced the blocking invoke.
  `stream_crew` yields a state snapshot per step; `run_crew` keeps the last one,
  so the app and the eval share one implementation. The app shows each agent as
  it finishes.
* Versions are kept current: langgraph 1.2.11, langchain-core 1.6.0,
  langchain-google-genai 4.3.5, langsmith 0.11.1, streamlit 1.62.0.

Kept hand-written on purpose: the retry in `llm.ask`. It reads the "try again in
Xs" out of a 429 and waits exactly that. A generic exponential backoff was tried
and measured - it left four of ten reports as stubs, because Groq's
tokens-per-minute window is longer than the backoff reached.
