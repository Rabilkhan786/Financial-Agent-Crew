# InvestPanel

> **Portfolio project.** A multi-agent investment-research system built to explore one
> idea end to end: *can a team of specialist agents plus an "analyst" that cross-checks
> their findings catch contradictions a single LLM pass would miss?* It's a learning /
> demonstration project, not a production service — see [Scope](#scope--what-this-is-and-isnt).

A **manager** dispatches **financial**, **news**, and **risk** specialists in parallel, then
an **analyst agent checks whether their findings actually agree** before writing a report —
and loops back with a specific follow-up when the numbers and the narrative disagree.

> ⚠️ **Informational analysis only — not investment advice.** Not a recommendation to buy,
> sell, or hold any security. Consult a licensed financial advisor before investing.

---

## What this project demonstrates

- **Multi-agent design with a real purpose** — not "agents for the sake of agents." The
  analyst's cross-check is the reason the system exists, and it's built as explicit,
  testable logic, not a vague prompt.
- **Evaluation-first engineering** — the metrics harness and a single-LLM baseline were
  built *before* the agents, so "does the extra machinery help?" is measured, not assumed.
- **Typed contracts everywhere** — every agent boundary is a Pydantic model; rules like
  "no unsourced facts" and "the disclaimer can't be removed" are enforced in code and tested.
- **Honest, reproducible results** — every number comes from a re-runnable script; none are
  hand-written.
- **Pragmatic API integration** — direct HTTP (no MCP, no vendor SDKs), disk-cached, with a
  swappable LLM factory (Gemini / OpenAI / Anthropic / Groq / DeepSeek / OpenRouter).

---

## The centerpiece: the analyst catching a real contradiction

A live run on **Tesla** (real data, free model). The financial agent found revenue **−2.9%**
and profit **−46.8%**, yet a **P/E of 278** — and the analyst caught the tension a single
summary would gloss over:

```
Contradictions found: 1 (follow-ups run: 2)
  financial vs news: Valuation is rich (P/E 278) but the fundamentals are shrinking
  (revenue/profit declining) — the price implies growth the numbers don't show.
      → asked news: "What justifies the premium valuation despite declining revenue/profit?"
```

The follow-up made the News agent go find the forward-looking story (AI / autonomy / energy)
that the market is pricing in — the loop working exactly as intended. On **Apple**, whose
numbers told a consistent story, the analyst correctly reported **0 contradictions**.

---

## Results

**Demonstrated qualitatively on live data** (the honest, reproducible part with a free API tier):

- **Analyst catches a real contradiction** — Tesla, above: P/E 278 vs profit −47%, flagged and
  followed up. This is the system's whole reason for existing, working end to end.
- **No false alarms** — Apple, whose numbers told a consistent story, correctly returned
  **0 contradictions**.
- **Every number is sourced** — 9 financial metrics per company computed in Python from FMP,
  risk from price history, news from fetched articles.

**Quantitative baseline vs panel** (real run, `n = 11` of 34 — a free daily token limit
stopped the rest; produced by `eval/run_eval.py`, never hand-written):

| System | Reasoning quality (0–1) | Contradiction catch rate | Confidently wrong |
|---|---|---|---|
| Single LLM + search | **0.77** | **0.83** (5/6) | 0.00 |
| InvestPanel | 0.48 | 0.50 (3/6) | 0.00 |

_(Cost ≈ $0 on the free tier; per-question latency wasn't recorded in this run.)_

**Honest finding: in this configuration the single-LLM baseline outscored the multi-agent
panel.** This project's rule is to report that, not bury it. The most likely cause is a known
**confound**: the data providers return **current** fundamentals, but the benchmark questions
and their "reasonable reads" are framed **historically** — so the panel's precise present-day
report is penalized against a past-dated answer key, while the baseline's web-search answer
aligns more with the historical framing. Note the panel's core skill *does* work on current
data (the Tesla contradiction above). A fair comparison needs point-in-time data, which is out
of scope here. Details and caveats: [`docs/evaluation.md`](docs/evaluation.md). To reproduce or
run the full 34:

```bash
uv run python -m eval.run_eval
```

---

## Why not just one AI?

A single LLM pass usually reviews each source separately and writes a fluent summary without
noticing when the numbers and the narrative disagree. InvestPanel splits research from
*checking*: the analyst compares specific claims across the specialists and, on a mismatch,
sends one pointed follow-up to one specialist. Whether that beats a single-LLM baseline is
measured, not assumed.

## Architecture

```
question -> [Manager] -> [Financial] [News] [Risk] (parallel) -> [Analyst]
                                                                     |
                                              contradiction? -> follow up ONE
                                              specialist (max 2 rounds), else
                                                                     |
                                                                 [Report] (+ disclaimer)
```

- **Manager** — reads the question, sets scope, finds real competitors via search.
- **Financial** — fundamentals from FMP; every number computed in Python (never by the LLM), each sourced.
- **News** — searches Tavily and summarizes real articles, each with its source URL.
- **Risk** — volatility and max drawdown computed in pure Python from price history (no separate API).
- **Analyst** — cross-checks the three, loops back on a real contradiction, writes the report.

Details: [`docs/architecture.md`](docs/architecture.md) ·
[`docs/agent_contracts.md`](docs/agent_contracts.md) ·
[`docs/interview_notes.md`](docs/interview_notes.md).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env      # then add your keys to .env
```

You need **one LLM provider key** plus the three data keys. The LLM is swappable — set
`LLM_PROVIDER` in `.env` to `gemini` | `openai` | `anthropic` | `groq` | `deepseek` |
`openrouter`. A free option: an [OpenRouter](https://openrouter.ai/keys) key with a free
model (this project was demoed on one).

| Variable | For |
|---|---|
| `LLM_PROVIDER` + that provider's key | the LLM (e.g. `OPENROUTER_API_KEY`) |
| `FMP_API_KEY` | fundamentals — [FMP](https://site.financialmodelingprep.com/developer/docs) |
| `ALPHAVANTAGE_API_KEY` | price history — [Alpha Vantage](https://www.alphavantage.co/support/#api-key) |
| `TAVILY_API_KEY` | news search — [Tavily](https://app.tavily.com/) |

```bash
uv run python check_gate0.py                 # verify all APIs are reachable
uv run python run.py "Is Tesla a reasonable long-term investment?"
uv run streamlit run app.py                  # the interactive demo (research + observability tabs)
uv run pytest -q                             # 42 tests, all mocked (no API calls)
```

## Scope — what this is and isn't

**Is:** a portfolio project showcasing multi-agent design, an evaluation harness, typed
contracts, and honest measurement. It runs, it's tested, and its core claim is demonstrated
on live data.

**Isn't:** a production service. Deliberately out of scope: live deployment, CI/CD,
authentication, request scaling/queuing, point-in-time historical data, and broad market
coverage. See below for what production would need.

### What production would need (deliberately not built)
- Point-in-time data (the current providers return latest fundamentals, so the eval is a
  systems comparison, not a rigorous backtest).
- A larger, second-reviewed question set and human-validated labels.
- Real token-cost accounting, rate-limit handling/backoff, and observability at scale.
- Auth, deployment, and CI/CD.

## Limitations

- Reasoning quality is scored by an LLM judge, which has its own biases.
- Coverage is limited to large, well-documented companies where the data is reliable.
- **Not predictive of future prices — never read it as such.**

## What I learned

Building the eval harness *before* the agents forced the honest question — does the extra
machinery actually help? Running it on live data also surfaced real bugs worth fixing (FMP's
retired v3 API, a date-parsing gap that dropped all news, and a competitor failure that wiped
the target's financials) and a genuine gap in the cross-check (it under-caught the
"expensive-but-shrinking" contradiction until a detector was added — found via the Tesla run).
That loop — build, measure on reality, fix — is the point.
