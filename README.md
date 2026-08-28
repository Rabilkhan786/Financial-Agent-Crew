# Financial Analysis Agent Crew

Type a stock ticker into a Streamlit app. Five agents research the company and
produce a fundamental analysis report, shown in the app and downloadable as a PDF.

**This is informational analysis, not investment advice.** Every report carries
that disclaimer as fixed text.

---

## What it does

```
START -> orchestrator -> ticker confirmed? --no--> END (clean error, no further calls)
                       |
                      yes
                       v
                market_researcher -> fundamentals_analyst -> data_analyst
                                                                    |
                                                                    v
                                                            report_writer
                                                                    |
                                                                    v
                                                          orchestrator_review
                                                          |-> fundamentals_analyst (revise)
                                                          |-> market_researcher   (revise)
                                                          |-> END
```

| Agent | Job |
|---|---|
| `orchestrator` | Confirms the ticker is real, names the company, sets the plan |
| `market_researcher` | News headlines and retail chatter, and what the mood is |
| `fundamentals_analyst` | Reads the statements and explains the ratios |
| `data_analyst` | Price performance, risk, and the five charts |
| `report_writer` | Writes the report from what is already in the state |
| `orchestrator_review` | Looks for contradictions and sends work back if needed |

A ticker Yahoo cannot confirm is routed straight to `END` from `orchestrator`
— `market_researcher`, `fundamentals_analyst`, `data_analyst` and
`report_writer` never run, so an invalid ticker costs one profile lookup, not
five agents' worth of wasted network calls.

---

## Running it

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv pip install -r requirements.txt
cp .env.example .env        # then put your Groq key in it
uv run --no-project streamlit run app.py
```

With Docker:

```bash
docker build -t crew .
docker run --env-file .env -p 8501:8501 crew
```

Verified: the image builds at 983MB, serves the app on 8501, reads the keys from
`--env-file`, reaches Yahoo Finance, and runs the full test suite inside the
container. Keys are never baked into the image.

Tests and the eval:

```bash
uv run --no-project python -m pytest tests/ -q          # fast: offline, no key needed
uv run --no-project python -m pytest tests/ -q --live    # adds 20 tests that call Groq and Yahoo
uv run --no-project python -m evals.run_eval             # all 10 companies
uv run --no-project python -m evals.run_eval AAPL MSFT   # or just a subset
```

The fast suite is 141 tests and runs in a few seconds with no network and no
`GROQ_API_KEY`. `conftest.py` skips anything marked `@pytest.mark.live` unless
`--live` is passed, so a fresh clone can run the whole fast suite immediately.

---

## Keys

Only one is required.

| Key | Needed? | What it gives you |
|---|---|---|
| `GROQ_API_KEY` | **yes** | The model every agent uses. Free |
| — | — | Yahoo Finance needs no key: prices, statements, news |
| — | — | StockTwits needs no key: retail sentiment |
| `FINNHUB_API_KEY` | no | Better news than Yahoo headlines (US listings on the free plan) |
| `ALPHAVANTAGE_API_KEY` | no | A sentiment score per article |

Missing optional keys switch features off; they never stop a run. The sidebar
shows which sources are live.

### Choosing a model

`GROQ_MODEL` in `.env`. The default is `openai/gpt-oss-120b`.

**Which models a key can reach varies by account.** A replacement key had 13
models and no llama at all, so a name that had worked the day before returned
404 on every call. List the models for the key in hand rather than trusting a
name:

```bash
curl -H "Authorization: Bearer $GROQ_API_KEY" -H "User-Agent: crew"      https://api.groq.com/openai/v1/models
```

`groq/compound` looks tempting at 70,000 tokens/minute against 8,000, but it is
an agentic model that runs its own web searches. It is not used here: it would
put numbers in front of the writer that the sourcing guard never saw.

---

## Design decisions

### The LLM never does arithmetic

Every number in the report is calculated in `src/tools/ratios.py` and
`src/tools/kpi.py` using plain pandas and numpy. Those two files import nothing
but numpy and pandas — no model, no network — and a **test parses their own
import statements to prove it**, so a future edit that reaches for either fails
the test suite instead of shipping.

The model receives the finished numbers and is asked what they mean. That
matters because a wrong figure in a financial report is worse than no figure,
and arithmetic done in code can be re-checked with a calculator. `ratios.py`
and `kpi.py` between them have 83 dedicated tests, and every one of those 83
asserts a value worked out by hand first, not just checked against the code's
own output.

### Red flags are rules, not opinions

Nine deterministic checks in `ratios.py`, with the thresholds as named
constants at the top of the file where they can be argued with — cash
conversion under 70% for three years running, debt to equity over 2.0,
interest cover under 2x, and so on. Each flag quotes the numbers that set it
off, so the writer states a figure it never had to work out.

The reviewer then checks, in Python, that every flag actually appears in the
report. A report that quietly drops a bad finding gets sent back.

### Invented numbers are rejected, not just noticed

`src/tools/sourcing.py` is a numerical sourcing guard: deterministic, no LLM
and no network, checking that every figure in the report traces back to
either a calculation or a headline the crew actually fetched. Anything else the
model brought from its own memory, and the reviewer sends the report back.
This is a validation check on one report at a time, not a mathematical
guarantee about the model's behaviour in general.

This was written because it kept happening. In one run a real headline said
Yes Bank profit "rose 34%" and the report turned it into "34-45%" - the 34 was
sourced, the 45 was invented to make a tidy range. Elsewhere a price target of
1,199 and a "$20 billion capital raise" appeared, neither in any fetched
article. Telling the model not to do this in the prompt was not enough.

The reviewer and the eval call the same function, so the eval measures the
guard the app actually runs rather than a copy of it that can drift.

### Why LangGraph and not a chain

Because of one edge: `orchestrator_review` can send the work **back** to an
earlier agent. A chain runs forwards only. The review is a conditional edge
returning one of three strings — `fundamentals_analyst`, `market_researcher`,
or accept — and that loop is the reason a graph is the right shape here.

### Why the loop is capped

Two agents can disagree forever. The review node checks
`revision_count >= max_revisions` **at the top, before anything else**, and
force-accepts the report when the cap is hit. Behind that, `recursion_limit=25`
is passed as a run setting to `crew.stream(..., stream_mode="values")` (the
same call `run_crew` and the Streamlit app both use) as a backstop in case the
routing itself misbehaves. Both were tested directly: at the cap the reviewer
accepts without even calling the model.

The app's Agent log tab shows this happening rather than leaving it in the
raw log text: each reviewer entry is marked "sending work back" or "accepted"
based on where it falls in the log (an acceptance is always the *last* entry;
a send-back is always followed by the agent it targeted), not by parsing the
reviewer's wording, and a closing line states plainly whether the report was
accepted on the first draft, after some revisions, or because the cap was hit.

### Missing data is reported, never inferred

Common for smaller listings and for companies that report unusual line items.
Anything Yahoo does not report comes back
as `None`, is named in an `unavailable` list, and is printed in the report as
unavailable. Ratios with a zero or negative denominator are left blank rather
than shown — return on equity when equity is negative looks like a real number
but means nothing.

### Social sentiment is counted, not guessed

StockTwits posts carry a Bullish/Bearish tag the poster set themselves, so the
mood is *counted* in Python. Below five posts the posts are **discarded** and
`social_sentiment` is hardcoded to `"insufficient data"` before the model sees
anything — a handful of anonymous posts is not a signal, and the surest way to
stop a model reading meaning into noise is to not show it the noise.

### Everything external is cached

`src/cache.py` stores every fetch on disk, keyed by ticker and date. Re-running
an analysis costs nothing. If a provider fails and a stale copy exists, the
stale copy is used rather than killing the run.

### Live, cached, or unavailable — shown, not hidden

Every tab in the app carries a small caption saying whether that section's
figures were fetched during this run, reused from an earlier one, or never
arrived at all — `cache.freshness()` compares the cache file's age against a
five-second "just fetched" window. A reader should not have to guess whether
a red flag is based on this morning's numbers or last week's.

### Every metric carries its own evidence

The Fundamentals and Price & market tables show Period, Source and Formula
next to every figure, from a small lookup in `formatting.py`
(`EVIDENCE`/`evidence_for()`). Two tests guard it against drifting from the
real calculations: one enumerates every key `ratios.ALL_RATIOS` actually
produces, the other every key `kpi.compute_all()` does, and asserts each has
a real entry — so a renamed or newly added ratio fails the test suite rather
than silently showing a blank evidence row.

---

## What it computes

**From the statements** — revenue growth YoY and 3-year CAGR, operating margin,
net margin, cash conversion (OCF ÷ net profit), free cash flow, debt to equity,
interest coverage, ROCE, ROE, and P/E and P/B against the company's *own*
5-year median.

Comparing a company with itself sidesteps the argument about which rivals count
as comparable. A negative multiple is reported as "not meaningful", not as cheap.

**From the prices** — total return, CAGR, annualised volatility, max drawdown,
Sharpe, the 50 and 200-day averages, and return against the right index. The
benchmark is chosen from the ticker suffix (`.NS` → NIFTY, `.BO` → SENSEX,
otherwise S&P 500), because beating "the market" only means something if it is
the right market. Stock and index are trimmed to shared trading days before
comparison. The project targets US listings; the suffix routing means a London
or Indian ticker still works, it is simply not what the eval covers.

---

## Evaluation

`evals/run_eval.py` runs ten US companies and checks three things per report.
Five are healthy (AAPL, MSFT, JNJ, KO, PG) and five are chosen to set off the
red-flag rules — Boeing is heavily borrowed with thin interest cover, Ford and
AT&T carry heavy debt, Intel burns cash, and Lumen manages negative equity,
high leverage, thin interest cover and falling revenue all at once. An eval
where nothing is ever flagged proves nothing:

1. **No blanks.** A NaN reaching the report means a calculation failed quietly.
2. **No invented numbers.** Every figure in the report must trace back to a
   calculated value. This is the check that proves the model is not doing maths.
3. **All sections present.**

Each company also gets one of four classifications: `PASS`, `FAIL`,
`DATA_UNAVAILABLE` (Yahoo had nothing for the ticker), or `PROVIDER_LIMIT`
(the model never answered — almost always the free tier's daily or per-minute
token limit). The three checks above measure report quality; the
classification keeps a provider outage from being reported as if it were a
bug in the crew.

Walgreens (`WBA`) used to be in the roster and was dropped: it was taken
private, so Yahoo now has no data for it at all. That would show up as
`DATA_UNAVAILABLE` — a real thing to know, but not a finding about the crew,
which is exactly the distinction the classification exists to make.

### Results

Measured 2026-08-26 on Groq `openai/gpt-oss-120b`, run in two batches of five
because of the daily token allowance.

| Check | Result |
|---|---|
| No blanks (NaN) | **10 / 10** |
| No unsourced numbers | **10 / 10** |
| All sections present | **8 / 10** |

| Ticker | Blanks | Numbers | Sections | Revisions |
|---|---|---|---|---|
| AAPL | pass | pass | pass | 0 |
| MSFT | pass | pass | pass | 0 |
| JNJ | pass | pass | pass | 0 |
| KO | pass | pass | pass | 0 |
| PG | pass | pass | pass | 0 |
| F | pass | pass | pass | 0 |
| T | pass | pass | pass | **1** |
| INTC | pass | pass | pass | 0 |
| BA | pass | pass | pass | 0 |
| LUMN | pass | pass | pass | 0 |

**The two failures were not report quality.** The free tier allows 200,000
tokens a day. The daily quota ran out at 14:33 and those two companies were
written at 14:28 and 14:32, so the writer got no answer and the report was
printed with its calculated sections only. The same tickers pass on a fresh
quota. It is a limit of the free plan, not of the crew, and it is left in the
table rather than quietly re-run until it looked better.

AT&T needed **one revision**: the reviewer rejected the first draft and sent the
work back, which is the loop doing what it exists for on real data.

### Why the guards matter

The unsourced-number check earns its place. Before it existed these reached the
reader: a `1,199` price target, a `$20 billion` capital raise, and a sourced
"34% jump in profit" widened into an invented "34-45%" range. None of those
figures appeared in any article the crew fetched.

Prompting alone did not stop it. The prompts now name the failure explicitly and
the guard still fires, which is the argument for having both.

Getting a trustworthy number out of the check meant fixing five false positives
first: dates in both ISO and prose form, thousands separators splitting
`3,807.45` into two numbers, index names like `S&P 500`, the Alpha Vantage
sentiment score, and the StockTwits tally (counted in Python, so
`16 out of 30 posts` is a calculated figure). Reports also use narrow no-break
spaces, which stopped the index names matching until the text was normalised. A
noisy check hides the real findings.

### Known limit: the free tier

Two separate limits, and the second is the one that bites.

**Tokens per minute** (8,000). `llm.py` paces calls with LangChain's
`InMemoryRateLimiter` and keeps `.with_retry()` behind it.

**Tokens per day** (200,000). One company costs roughly 15,000-20,000 tokens, so
about ten to twelve companies fit in a day. A ten-company eval fits once; running
it repeatedly does not. When the daily quota goes, the writer gets no answer and
the report comes back with only its calculated sections - which looks exactly
like a code fault and is not one. `GROQ_MODEL` can be pointed at another model,
each of which has its own daily budget.

Also worth knowing: a reasoning model can spend its whole output budget thinking
and return an empty answer, which is why `MAX_OUTPUT_TOKENS` and
`REQUEST_TIMEOUT` are set explicitly rather than left at their defaults.

---

## Limitations

Honest, not exhaustive:

- **Free-tier limits, above.** The daily token cap is the one most likely to
  bite during a portfolio demo — run one or two companies rather than the
  full ten if the quota is uncertain.
- **The disk cache stores pickled Python objects**, not JSON, because a cached
  value can be a pandas DataFrame. `pickle.load` on untrusted input is a known
  risk in general; here it is not one in practice, because nothing but this
  app's own fetch functions ever writes to `.cache/`. It would matter if that
  stopped being true.
- **yfinance's `history()` call has an explicit timeout** (`market_data.py`,
  `REQUEST_TIMEOUT = 20`); `.info`, the statements, and `.news` do not, because
  yfinance exposes no timeout parameter on those and a custom `requests.Session`
  was tried and rejected — it bypasses yfinance's own cookie/crumb handling and
  gets rate-limited immediately, verified live. A hung connection on those
  calls would still hang the agent that made it, and fixing that properly
  means either a thread-based timeout wrapper or tracking yfinance's own
  session internals, both bigger than this project's scope justifies without
  an actual incident.
- **US listings only, by design.** The `.NS`/`.BO`/`.L`/`.TO` benchmark
  routing in `kpi.py` works for other exchanges and is unit tested, but the
  eval roster, the README's examples, and the orchestrator's ticker-confirmed
  message are all written with US tickers in mind.
- **No demo screenshot in this README.** Verified live in a browser during
  development (sidebar, invalid-ticker handling, the evidence table, all
  checked against a real running instance), but capturing and committing an
  actual image is a manual step, not something to fake with a placeholder.

---

## Tech stack

Everything here is in `requirements.txt` — nothing here is aspirational.

**Agents and orchestration** — LangGraph, LangChain, Groq (`langchain-groq`),
pydantic (structured reviewer output)
**Data and maths** — pandas, numpy, yfinance
**Optional data sources** — Finnhub, Alpha Vantage, StockTwits (all via plain
`urllib`, no client SDK for any of them)
**Output** — Streamlit, Matplotlib, fpdf2
**Config and tests** — python-dotenv, pytest

---

## Layout

```
app.py                     the Streamlit app
src/config.py              the only file that reads .env, plus logging
src/state.py               the shared TypedDict every agent reads and writes
src/llm.py                 the only file that talks to Groq
src/graph.py               the LangGraph wiring
src/cache.py               disk cache for every external call
src/charts.py              the five matplotlib charts
src/report_pdf.py          the PDF export
src/formatting.py          numbers to readable text
src/agents/                the five agents plus the reviewer
src/tools/ratios.py        fundamental maths (pure pandas/numpy, tested)
src/tools/kpi.py           price maths (pure pandas/numpy, tested)
src/tools/sourcing.py      numerical provenance guard (pure stdlib, tested)
src/tools/statements.py    Yahoo line items to our column names
src/tools/market_data.py   prices, benchmark, profile, valuation history
src/tools/news.py          Yahoo / Finnhub / Alpha Vantage
src/tools/social.py        StockTwits (keyless)
tests/                     141 fast tests + 20 live tests (see Testing, below)
evals/run_eval.py          ten companies, three checks, four-way classification
output/                    reports, charts, logs (gitignored)
```

---

## Notes from building it

Things found by running the code, not by reading docs:

- **Which models a Groq key can reach varies by account.** A key that had 13
  models and no llama at all returned 404 on a model name that worked fine on
  a different key the day before. List the models for the key in hand.
- **`.with_retry()` on a model removes `.with_structured_output()`** — calling
  it on an already-retrying model raises, because the retry wrapper does not
  carry that method through. The fix is to build the structured chain first
  and put `.with_retry()` on the outside (`src/llm.py:ask_structured`).
- **A reasoning model can spend its whole output budget thinking** and return
  an empty answer, which reaches the reader as "the report could not be
  written." `MAX_OUTPUT_TOKENS` and `REQUEST_TIMEOUT` are set explicitly
  because of this.
- Finnhub's free plan returns **403** for non-US tickers, so `news.py` falls back
  to Yahoo on any error, not just on an empty result.
- StockTwits returns 404/403 for tickers it has no page for, which is expected
  and yields "insufficient data" rather than an error.
- Yahoo's statement row labels are consistent across exchanges, so one field map
  covers US listings and everything else alike.
