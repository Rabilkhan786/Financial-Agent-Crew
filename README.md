# Financial Analysis Agent Crew

Type a stock ticker into a Streamlit app. Five agents research the company and
produce a fundamental analysis report, shown in the app and downloadable as a PDF.

**This is informational analysis, not investment advice.** Every report carries
that disclaimer as fixed text.

---

## What it does

```
START -> orchestrator -> market_researcher -> fundamentals_analyst
      -> data_analyst -> report_writer -> orchestrator_review
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

Tests and the eval:

```bash
uv run --no-project python -m pytest tests/ -q
uv run --no-project python -m evals.run_eval
```

---

## Keys

Only one is required, and which one depends on `LLM_PROVIDER`.

| Key | Needed? | What it gives you |
|---|---|---|
| `GROQ_API_KEY` | **yes, by default** | Groq. Free, and fast enough to run the whole eval |
| `GOOGLE_API_KEY` | only if `LLM_PROVIDER=gemini` | Gemini. Free tier is 20 requests/day per model |
| — | — | Nothing at all if `LLM_PROVIDER=ollama`: the model runs on your machine |
| — | — | Yahoo Finance needs no key: prices, statements, news |
| `FINNHUB_API_KEY` | no | Better news than Yahoo headlines (US listings only on the free plan) |
| `ALPHAVANTAGE_API_KEY` | no | A sentiment score per article |
| `LANGSMITH_API_KEY` | no | Traces every run at smith.langchain.com |
| `REDDIT_CLIENT_ID` / `_SECRET` | no | Reddit posts instead of StockTwits |

Missing optional keys switch features off; they never stop a run. The sidebar
shows which sources are live.

### Choosing a model

`LLM_PROVIDER` takes `groq` (default), `gemini` or `ollama`. Only `src/llm.py`
reads it, so switching changes nothing else in the project.

| Provider | Per company | Ten-company eval | Key |
|---|---|---|---|
| **groq** | ~1 min | ~10 min | free |
| gemini | ~1 min | cannot finish in a day (20 req/day) | free |
| ollama | ~8-10 min | ~90 min | none, runs locally |

Ollama timings were measured on an i5-1334U laptop with no discrete GPU running
`qwen3:8b` at 6.2 tokens/sec. It needs `reasoning=False`, or qwen3 leaks
`/think` markers into the report. Worth having because it needs no key at all;
too slow to run the eval with.

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
and arithmetic done in code can be re-checked with a calculator. All 83 unit
tests assert values worked out by hand first.

### Red flags are rules, not opinions

Nine deterministic checks in `ratios.py`, with the thresholds as named
constants at the top of the file where they can be argued with — cash
conversion under 70% for three years running, debt to equity over 2.0,
interest cover under 2x, and so on. Each flag quotes the numbers that set it
off, so the writer states a figure it never had to work out.

The reviewer then checks, in Python, that every flag actually appears in the
report. A report that quietly drops a bad finding gets sent back.

### Invented numbers are rejected, not just noticed

`src/tools/sourcing.py` checks that every figure in the report traces back to
either a calculation or a headline the crew actually fetched. Anything else the
model brought from its own memory, and the reviewer sends the report back.

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
is passed to `graph.invoke` as a backstop in case the routing itself misbehaves.
Both were tested directly: at the cap the reviewer accepts without even calling
the model.

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
red-flag rules — Boeing has negative equity, Ford and AT&T carry heavy debt,
Intel burns cash, Walgreens has falling revenue. An eval where nothing is ever
flagged proves nothing:

1. **No blanks.** A NaN reaching the report means a calculation failed quietly.
2. **No invented numbers.** Every figure in the report must trace back to a
   calculated value. This is the check that proves the model is not doing maths.
3. **All sections present.**

### Results (10 companies, Groq `openai/gpt-oss-120b`)

| Check | Result |
|---|---|
| No blanks | **10 / 10** |
| All sections present | **10 / 10** |
| No unsourced numbers | **8 / 10** |

The two failures are real and worth reading. Infosys quoted an analyst target
of `1,199` and YesBank turned a sourced "34% jump in profit" into an invented
"34-45%" range. Neither figure appears in any article the crew fetched, so the
model supplied them from its own knowledge despite being told not to. The check
exists to catch exactly that.

Getting there meant fixing five false positives in the checker first: dates in
both ISO and prose form, thousands separators splitting `3,807.45` into two
numbers, index names like `S&P 500`, the Alpha Vantage sentiment score, and the
StockTwits tally (which is counted in Python, so `16 out of 30 posts` is a
calculated figure). Reports also use narrow no-break spaces, which stopped the
index names matching until the text was normalised. A noisy check hides the
real findings.

### Known limit: free-tier rate limits

A full run needs roughly five model calls per company. The free tier allows
**20 requests per day per model**, so a ten-company eval cannot complete in one
day on one model. Options: run it in batches across days, point
`GEMINI_MODEL` at a different model (each has its own daily quota), or use a
paid key. When the quota runs out mid-run the report writer gets no response and
the report comes back as a short stub — visible in the eval as missing sections.

---

## Layout

```
app.py                     the Streamlit app
src/config.py              the only file that reads .env, plus logging
src/state.py               the shared TypedDict every agent reads and writes
src/llm.py                 the only file that talks to Gemini
src/graph.py               the LangGraph wiring
src/cache.py               disk cache for every external call
src/charts.py              the five matplotlib charts
src/report_pdf.py          the PDF export
src/formatting.py          numbers to readable text
src/agents/                the five agents plus the reviewer
src/tools/ratios.py        fundamental maths (pure pandas/numpy, tested)
src/tools/kpi.py           price maths (pure pandas/numpy, tested)
src/tools/statements.py    Yahoo line items to our column names
src/tools/market_data.py   prices, benchmark, profile, valuation history
src/tools/news.py          Yahoo / Finnhub / Alpha Vantage
src/tools/social.py        StockTwits or Reddit
tests/                     83 unit tests over the two maths modules
evals/run_eval.py          ten companies, three checks
output/                    reports, charts, logs (gitignored)
```

---

## Notes from building it

Things found by running the code, not by reading docs:

- `gemini-2.5-flash` returns 404 for new API keys — it is retired for new users.
  Working models include `gemini-3.5-flash` (the default here) and
  `gemini-3.6-flash`. 3.6 silently ignores the temperature setting; 3.5 respects it.
- Gemini 3 returns `message.content` as a **list of blocks, not a string**.
  `llm.text_of()` flattens it, or every caller breaks on `.strip()`.
- Finnhub's free plan returns **403** for non-US tickers, so `news.py` falls back
  to Yahoo on any error, not just on an empty result.
- Reddit blocks unauthenticated JSON entirely (403 on every endpoint), which is
  why StockTwits is the keyless default.
- Yahoo's statement row labels are consistent across exchanges, so one field map
  covers US listings and everything else alike.
