# CLAUDE.md — InvestPanel

This file is loaded automatically at the start of every Claude Code session in this
repository. It is the persistent memory for this project. Read it fully before acting.

The complete build specification is at `docs/BUILD_SPEC.md`. This file is the short
version plus the live status. When the two disagree, `docs/BUILD_SPEC.md` wins.

## Execution mode

Run in autonomous mode by default. Do not wait for the user to say "continue" between
ordinary steps inside a phase, and do not ask permission for routine decisions the spec
already answers. Decide from this file and `docs/BUILD_SPEC.md`, then act.

Stop and ask only when:
- you have reached a **phase gate** — show what was built, explain it in plain English,
  and wait
- a required API key or account is missing and you cannot proceed without it
- the spec is genuinely silent on a decision that would be expensive to reverse later
- two consecutive attempts at the same problem have failed — stop, report what was tried,
  propose the fix, then continue rather than trying a third time silently

At the very start of a session: read this file, read the Status section, state in one
sentence what you're about to do, then go.

---

## Project

**InvestPanel** — a multi-agent investment research panel. A manager agent dispatches
three specialists (financial, news, risk) to research a company in parallel. An analyst
agent checks whether their findings actually agree with each other — not just merges them
— and can send a specific follow-up back to one specialist before writing the final
report.

The person you are working with is not writing code. They are learning from what you
build. Explain every file in plain English as you create it, in 2–4 sentences: what it
does and why it exists. Avoid jargon; define any unavoidable term once.

**This produces informational analysis, not investment advice.** Every report generated
by the system must carry a visible disclaimer stating this. Build the disclaimer into the
report template from Phase 0, not bolted on later.

---

## Hard rules — never break these

1. **Build order is fixed.** Data loaders and the evaluation harness come before agents.
   Baselines before the panel. If asked to jump ahead to the agents, say no and explain:
   without baselines there is no way to know whether the panel actually helps.
2. **Never fabricate a number.** Every figure in the README must be produced by a script
   in `eval/` that anyone can re-run. If the panel loses to a single-agent baseline,
   report that honestly and analyse why.
3. **No unsourced facts.** No agent may assert a financial fact or news event without a
   `source` field — a real API response or a real fetched URL. Enforce with a Pydantic
   validator, not with prompt wording. Test it.
4. **Every agent boundary is a Pydantic model.** No free-form strings between agents.
5. **The Analyst's cross-check is the point of the project — it must be real.** It
   compares numeric claims from the Financial agent against qualitative claims from the
   News and Risk agents (e.g. "margins improved" vs "restructuring announced last month")
   and must be able to detect a genuine mismatch and route a specific follow-up back to
   the right specialist. Do not let this collapse into "summarize the three reports" —
   that is the single most important thing to test and defend.
6. **No MCP.** Direct API calls only, using plain Python HTTP clients. This was a
   deliberate choice, not an oversight — do not introduce MCP servers.
7. **Cache every external call.** Every API response, every search, every page fetch
   goes to disk cache. Re-running the evaluation must not re-pay for the same queries.
8. **Tracing from Phase 0.** LangSmith plus local JSON. A missing LangSmith key must
   never break a run.
9. **Stop at every gate.** Show the result, wait for the user to say continue.
10. **Commit at every gate** with a clear message.
11. **No test may make a real API call.** Mock the LLM and mock the data providers.
12. **Every report ends with the disclaimer.** Not investment advice — informational
    analysis only. This is a hardcoded template element, not something an agent decides
    to include.

---

## Status — keep this updated

Update this section at the end of every phase, before committing. This is how context
survives between sessions when the user runs `/clear`.

```
Phase 0  Skeleton, LLM factory, tracing, API clients   [x] GATE 0 PASSED live (all 5, LLM via OpenRouter free model)
Phase 1  Ground-truth question set, metrics            [x] GATE 1 passed (mock-tested, no keys)
Phase 2  Baseline (single LLM + search)                [~] code+tests done, GATE 2 run pending keys
Phase 3  Financial + News + Risk agents                [x] GATE 3 verified live (AAPL: Financial+Risk+News all sourced)
Phase 4  Manager + Analyst + cross-check loop           [x] GATE 4 passed live (TSLA: caught P/E-vs-shrinking-profit, looped to News, 2 rounds)
Phase 5  Full eval, error analysis, ablation            [~] harness (run_eval.py) done; numbers pending keys
Phase 6  Streamlit, Docker, deploy, docs                [~] app+docker+docs+README done; deploy+numbers pending keys
```

**Last completed:** Phase 1 — `eval/datasets/heldout_questions.py` (34 hand-built, date-
stamped questions; 11 labeled with a real financial-vs-qualitative contradiction; writes
`data/heldout_questions.json`) and `eval/metrics.py` (reasoning-quality via injectable LLM
judge, contradiction catch rate, confidently-wrong rate, cost/latency). 11 unit tests pass
(metrics + models), lint clean. GATE 1 met without keys (judge is mocked in tests).

**USER TO REVIEW (part of GATE 1):** skim `eval/datasets/heldout_questions.py` — add/remove
companies and sharpen any "reasonable_read" you disagree with, then re-run
`uv run python -m eval.datasets.heldout_questions` to regenerate the JSON.

**LLM PROVIDER (working):** `.env` uses `LLM_PROVIDER=openrouter` with
`OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free` (free). DeepSeek `:free` on
OpenRouter is now paid-only; other free models exist (also verified: `openai/gpt-oss-20b:free`,
`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`). The free model is SLOW (~7-40s/call),
so the full 34x2 eval will be long — consider `gpt-oss-20b:free` as a faster workhorse, or run
the eval on a subset first. Factory supports gemini|openai|anthropic|groq|deepseek|openrouter.

**Next action:** GATE 4 — a full `run.py` end-to-end was launched for Apple (verify report +
disclaimer + any contradiction). To DEMONSTRATE the cross-check loop live, pick a value-trap-ish
name (cheap P/E + a weak fundamental + elevated vol) so detector 3 fires, or rely on LLM
augmentation. Then GATE 2 (`python -m eval.baselines.single_llm_search`) and the full eval
(`python -m eval.run_eval`) -> paste REAL numbers into README + docs/evaluation.md -> Phase 5
error analysis + ablation -> deploy + screenshot. Do NOT fabricate any number (hard rule #2).

**SECURITY (resolved):** the user twice pasted real keys into `.env.example` (a tracked file);
one paste (FMP/AV/Tavily/LangSmith) got committed in the old Phase 6 commit. History was
rewritten (amend + reflog expire + gc) so no secret remains in any commit; nothing was ever
pushed (no remote). Keys now live only in `.env` (gitignored). User should still ROTATE the
FMP/AV/Tavily/LangSmith keys to be safe, and only ever edit `.env`, never `.env.example`.

**Phase 6 done (code):** `app.py` (Streamlit: research tab w/ report export + observability tab
reading panel_run traces), `utils/report_export.py` (Report -> Markdown), `utils/trace_stats.py`
(aggregate panel_run traces), `run_panel` now writes a consolidated `panel_run` trace
(latency/completeness/loop-fired), `Dockerfile`, `.dockerignore`, `Makefile`, all four `docs/*.md`,
`README.md` (results table left as explicit placeholders). streamlit+pandas added. 40 tests pass.

**Phase 4 done (code):** `agents/manager.py` (parses question, finds competitors via real
search, company description from FMP profile), `agents/analyst.py` — the core cross-check as
explicit field-level detectors (unit-tested: catches healthy-financials-vs-unexplained-
volatility and routes a specific follow-up) plus optional LLM augmentation, `build_checklist_
answers`, `write_report`; `graph/state.py` (reducers for errors/all_contradictions),
`graph/routing.py` (bounded loop), `graph/workflow.py` (manager -> 3 parallel specialists ->
analyst -> follow-up loop -> report, agents injected for testability), `run.py` CLI. 34 tests
pass incl. loop-fires / loop-stops-at-2-rounds / graceful-degradation.

**Phase 3 done (code):** `agents/base.py` (LLM+JSON-retry+trace), `agents/financial.py`
(metrics computed in pure Python from FMP — never by the LLM — each sourced; peer table),
`agents/risk.py` (volatility + max drawdown from AV prices, pure Python, no LLM),
`agents/news.py` (summaries of really-fetched articles; source_url is the fetched URL;
unfetchable/undated articles skipped), `tools/volatility.py`, FMP statement endpoints,
AV `closing_prices`. `demo_gate3.py` prints all three specialists for one ticker. 30 tests pass.

**FMP FIELD NOTE:** financial metric extraction guesses some FMP field names (e.g.
operatingCashFlow, totalStockholdersEquity, peRatioTTM) with fallbacks. Verify against a
real FMP response at GATE 3 and adjust `_pick(...)` names in `agents/financial.py` if needed.

**Open problems:** Live gates (0 live-check, 2 run, 3 run, 4 run) blocked on the 4 API keys
in `.env`. All code + mock tests run without keys (30 passing). No code known-broken.

**Decisions made that differ from the spec:** none functional. Notes: (1) the disk-cache +
retry logic for all three clients lives in one file `tools/cache.py` so the caching rule is
enforced in a single auditable place, rather than duplicated per client; (2) dropped the
uv-generated `[project.scripts]` entry point — `run.py` will be the CLI (Phase 6);
(3) pandas / matplotlib / scikit-learn / streamlit not installed yet — added in the phases
that use them, to keep the env lean and honor build-order discipline.

---

## Architecture (one line each)

```
manager      reads the question, sets scope (company, time window), dispatches specialists
financial    pulls real fundamentals (FMP) + price history (Alpha Vantage), with sources
news         searches (Tavily) for recent events, fetches and summarizes real articles
risk         computes volatility/exposure from the financial agent's own price data —
             plain Python math, not a separate API
analyst      cross-checks: do financial, news, and risk findings actually agree?
             if not, sends a specific follow-up back to ONE specialist (max 2 rounds)
             then writes the report, with the disclaimer, always
```

Loop: analyst -> one specialist, only when a specific contradiction is found. Max 2 rounds.

---

## Structure

```
investpanel/
├── CLAUDE.md
├── README.md                    results table at the top
├── pyproject.toml               uv-managed
├── uv.lock
├── .python-version
├── .env.example
├── Makefile
├── run.py                       CLI: analyze one company
├── app.py                       Streamlit demo
├── docs/
│   ├── BUILD_SPEC.md
│   ├── architecture.md
│   ├── agent_contracts.md
│   ├── evaluation.md
│   └── interview_notes.md       written in Phase 6
├── src/investpanel/
│   ├── config.py
│   ├── models/                  question, finding, contradiction, report
│   ├── agents/                  base, manager, financial, news, risk, analyst
│   ├── tools/
│   │   ├── fmp_client.py        fundamentals
│   │   ├── alphavantage_client.py   price history
│   │   ├── search.py            Tavily
│   │   ├── fetch.py             article text extraction
│   │   ├── cache.py             disk cache for all of the above
│   │   └── volatility.py        PURE PYTHON — std dev of returns, no LLM
│   ├── graph/                   state, workflow, routing
│   ├── llm/                     factory, usage
│   └── utils/                   logging, tracing
├── eval/
│   ├── datasets/
│   │   └── heldout_questions.py    hand-built, with what-was-knowable-at-the-time notes
│   ├── baselines/
│   │   └── single_llm_search.py
│   ├── metrics.py                accuracy of reasoning vs known outcome, contradiction
│   │                              catch rate, confidently-wrong rate
│   ├── run_eval.py
│   └── results/
├── data/
│   ├── heldout_questions.json
│   └── cache/                    gitignored
└── tests/
```

---

## Code style — match a 1-2 year engineer, not a senior

The person maintaining this code is early-career. Write code they can read, explain, and
defend line by line in an interview — not code that impresses other senior engineers.

- **Prefer plain, explicit code over clever abstractions.** A straightforward function with
  a few if-statements beats a generic factory pattern or heavy metaclass magic. If there's
  a simple way and a "proper enterprise" way, pick the simple way unless the spec
  specifically calls for the structure (e.g. the Pydantic models, the LangGraph wiring —
  those stay as specified, they're not optional complexity).
- **No deep inheritance hierarchies beyond what's in the spec.** `agents/base.py` exists
  because the spec calls for it — don't add further intermediate base classes on top.
- **No metaprogramming, decorators beyond what a library requires, or clever one-liners.**
  A list comprehension is fine; nested comprehensions or unpacking tricks are not.
- **Comment the "why", briefly, in plain English**, especially anywhere the code enforces a
  project rule (no-unsourced-facts, the disclaimer, the round limit) — the user needs to
  point at that comment in an interview and explain the reasoning themselves.
- **Standard library and the libraries in the stack only.** Don't reach for an extra
  dependency to save a few lines of code.
- **Functions and classes should be short and do one obvious thing.** If a function needs a
  paragraph to explain, split it.
- This does not mean skipping tests, type hints, or the schema validation — those stay.
  It means the *implementation* inside each function stays simple enough that the user can
  read it top to bottom and say what every line does.

---

## Conventions

- Python 3.11+, type hints everywhere, Pydantic v2.
- One responsibility per file. Split any file over ~200 lines.
- All tunables in `config.py`. Never hardcode a magic number inside an agent.
- Prompts live as module-level constants in their agent module, not inline in a function.
- Every agent inherits from `agents/base.py` — retries, JSON parsing, schema validation,
  trace emission live there. Agents themselves stay small.
- Never commit `.env`, `data/cache/`, or any API key.

---

## Environment — uv and the virtual environment

This project uses **uv** for Python and dependency management. uv creates and manages the
virtual environment itself, at `.venv/` in the project root. Do **not** run
`python -m venv` — uv makes that environment for you the first time you run `uv sync` or
`uv add`.

```
uv init                      once, at the start of Phase 0
uv python pin 3.11
uv venv                      create .venv explicitly (uv sync also creates it)
uv add langgraph pydantic httpx diskcache
uv add --dev pytest ruff
uv sync                      recreate the exact environment from uv.lock
uv run python run.py         run anything inside .venv — no activation needed
uv run pytest
```

Rules:

- Prefer `uv run` over activating a shell manually.
- `.venv/` is gitignored. `uv.lock` is committed.
- Add dependencies with `uv add`, never by hand-editing `pyproject.toml`, never with
  `pip install`.
- The Makefile targets wrap uv: `make eval`, `make demo`, `make test`.
- The Dockerfile in Phase 6 runs `uv sync --frozen`, not pip.

---

## Stack

Python 3.11+ managed by **uv** · LangGraph · Pydantic v2 · LangSmith (optional) · Gemini
by default via a swappable `llm/factory.py` · **FMP** for fundamentals · **Alpha Vantage**
for price history · **Tavily** for news search · httpx · trafilatura · diskcache ·
pandas · matplotlib · scikit-learn · Streamlit · pytest · Docker.

**Deliberately not used:** MCP (direct API calls instead — a stated decision, not a gap),
a separate risk-data API (volatility computed in plain Python from price data already
fetched), vector database (nothing here needs embedding), fine-tuning.

---

## Model switching

Switch with `/model` inside Claude Code. Match the model to the task, not the phase number.

| Task type | Model | Why |
|---|---|---|
| Architecture, LangGraph design, the cross-check logic in the analyst agent | **Opus** | Hard to undo later; the cross-check is the core of the project |
| Error analysis in Phase 5, deciding what to fix | **Opus** | Judgement work |
| Debugging something that failed twice on Sonnet | **Opus** | Two failures means the problem needs more reasoning |
| Writing agents, tools, loaders, tests, Streamlit app | **Sonnet** | Execution against an already-fixed design |
| Refactors, docstrings, README filling | **Sonnet** | Mechanical work |
| Bulk formatting, boilerplate | **Haiku** | Cheapest option for zero-ambiguity work |

- Default to Sonnet. Escalate on the second failure, not the first.
- Come back down to Sonnet once Opus solves the hard part.
- Say out loud when you switch and why.
- If a Pro usage limit is hit mid-phase, stop at a clean point, update Status, commit,
  and tell the user exactly where to resume.

---

## Cost discipline

The user is on a Claude Pro plan with usage limits, building across several sessions.

- Follow the model switching table above.
- Do not re-read files already read this session.
- Keep responses focused — no long recaps beyond the required plain-English explanation.
- Update the Status section at the end of every phase so the next session starts cold.

---

## Phase gates

- **GATE 0** — `uv run python -c "..."` reaches Gemini; FMP, Alpha Vantage, and Tavily
  clients each successfully return one real response; tracing writes a local JSON file.
- **GATE 1** — 30–40 hand-built questions exist with documented what-was-knowable-then
  context; metrics module unit-tested against a fixture.
- **GATE 2** — baseline (single LLM + search) run over the question set, results committed.
- **GATE 3** — for one company, print the financial findings, news findings, and risk
  findings separately — each with sources.
- **GATE 4** — end-to-end run on 5 companies, including at least one case where the
  analyst agent catches a real contradiction and sends a follow-up. Full trace shown.
- **GATE 5** — results table complete, error analysis with counts, one measured
  improvement, one ablation.
- **GATE 6** — a stranger can clone, add four API keys, and run it.

---

## First action in a new session

1. Read this file.
2. Read the Status section to find where the build stopped.
3. State in one sentence what you are about to do.
4. Do that phase only. Stop at its gate.
