# InvestPanel

A multi-agent investment research panel: a manager dispatches **financial**,
**news**, and **risk** specialists in parallel, and an **analyst agent checks
whether their findings actually agree** before writing a report — catching
contradictions a single-pass analysis would miss.

> ⚠️ **This is informational analysis only, not investment advice.** It is not a
> recommendation to buy, sell, or hold any security. Consult a licensed financial
> advisor before making investment decisions.

_Live demo: not yet deployed. Screenshot/GIF: added after the first live run._

## Results

Both systems are scored on the same 34-question benchmark with the same metrics.
The table is produced by `uv run python -m eval.run_eval` — the numbers below are
intentionally left blank until a real run fills them in (this project never
hand-writes a result number).

| System | Reasoning quality | Contradiction catch rate | Confidently wrong | Cost/question | Latency |
|---|---|---|---|---|---|
| Single LLM + search | _pending run_ | _pending run_ | _pending run_ | _pending run_ | _pending run_ |
| InvestPanel | _pending run_ | _pending run_ | _pending run_ | _pending run_ | _pending run_ |

## Why not just one AI?

A single LLM pass usually reviews each source separately and writes a fluent
summary without noticing when the numbers and the narrative disagree. InvestPanel
splits research from *checking*: an analyst agent compares specific claims across
the specialists and, on a mismatch, sends one pointed follow-up back to one
specialist. Whether that actually beats a single-LLM baseline is measured, not
assumed — see [`docs/evaluation.md`](docs/evaluation.md).

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
- **Financial** — fundamentals from FMP; numbers computed in Python, each sourced.
- **News** — searches Tavily, fetches real articles, summarizes them with sources.
- **Risk** — volatility and drawdown computed in pure Python from price history.
- **Analyst** — cross-checks the three; loops back on a real contradiction; writes the report.

More detail in [`docs/architecture.md`](docs/architecture.md) and
[`docs/agent_contracts.md`](docs/agent_contracts.md).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). Then:

```bash
uv sync
cp .env.example .env      # then paste your four keys into .env
```

Four free API keys go in `.env`:

| Variable | Get it from |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/app/apikey |
| `FMP_API_KEY` | https://site.financialmodelingprep.com/developer/docs |
| `ALPHAVANTAGE_API_KEY` | https://www.alphavantage.co/support/#api-key |
| `TAVILY_API_KEY` | https://app.tavily.com/ |

Then:

```bash
uv run python check_gate0.py                 # verify all four APIs are reachable
uv run python run.py "Is Apple a reasonable long-term investment?"
uv run streamlit run app.py                  # the interactive demo
uv run pytest -q                             # tests (all mocked, no API calls)
```

## Limitations

- Reasoning quality is scored by an LLM judge, which has its own biases.
- Coverage is limited to large, well-documented public companies where the data
  providers are reliable.
- **This is not predictive of future prices and must never be read as such.**

## What I learned / what's next

Building the evaluation harness *before* the agents forced an honest question —
does the extra machinery actually help? — instead of assuming it. Next: wire real
token-cost tracking into every run, run the model-independence ablation on the
analyst, grow and second-review the question set, and add cross-check detectors
from observed misses. See [`docs/interview_notes.md`](docs/interview_notes.md).
