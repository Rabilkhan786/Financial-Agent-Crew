# InvestPanel — Full Build Specification

**Paste this file into `docs/BUILD_SPEC.md` in your project.** Claude Code reads it
alongside `CLAUDE.md` at the start of every session.

---

## 1. Project summary

**Name:** InvestPanel

**One-line pitch:** A multi-agent investment research panel where a manager dispatches
financial, news, and risk specialists in parallel, and an analyst agent checks whether
their findings actually agree before writing a report — catching contradictions a
single-pass analysis would miss.

**The problem:** Researching whether a company is a reasonable investment means pulling
together financial fundamentals, recent news, and risk signals, and checking whether they
tell a consistent story. A single analyst, or a single AI pass, often reviews each source
separately without noticing when one contradicts another — healthy financials next to an
unexplained volatility spike, for example, with nobody asking why.

**The approach:** Adversarial-cross-check multi-agent research, same family as the
MedCollab-style pattern (specialists report independently, a synthesis agent checks their
work, loops back for more evidence when something doesn't add up).

**Success is defined by:** whether the analyst agent's cross-check catches contradictions
that a single-LLM-with-search baseline misses, measured against a hand-built set of real
historical questions.

**Non-negotiable framing:** this produces informational analysis, never investment advice.
Every report carries a visible disclaimer. State this plainly in the README.

## The 10-question checklist — this defines what "done" means

Every report the system produces must answer these 10 questions. This is the concrete
success criterion for the whole project — not "the report sounds thorough," but "every one
of these 10 has an answer with evidence behind it."

```
1.  What does the company do?                    -> Manager (company description, once)
2.  Is revenue growing?                           -> Financial (FMP income statement, YoY)
3.  Are profits growing?                          -> Financial (net income, YoY)
4.  Is operating cash flow healthy?                -> Financial (FMP cash flow statement —
                                                       catches profit that isn't backed by cash)
5.  Is debt manageable?                            -> Financial (debt-to-equity, interest coverage)
6.  Are ROCE / ROE healthy?                        -> Financial (computed from income + balance sheet)
7.  Durable competitive advantage?                 -> News + Analyst (qualitative — must be
                                                       evidenced, not asserted)
8.  Is management trustworthy and shareholder-friendly? -> News (insider selling, turnover,
                                                       governance signals, past claims vs results)
9.  What could seriously damage the business?      -> Risk + News (Risk computes exposure,
                                                       News finds the actual named threats)
10. Is the current price reasonable vs future earnings/cash flows? -> Financial + Risk
                                                       (P/E, P/B, growth-adjusted valuation)
```

Questions 2, 3, 4, 5, 6, and 10 are numeric — implement each as an explicit named field on
`FinancialFinding`, not a paragraph the agent free-writes. Questions 7, 8, and 9 are
judgment calls and are exactly where the no-unsourced-facts rule matters most: an agent
claiming "management is trustworthy" or "the moat is durable" without a cited article is a
validator failure, not a style choice.

The final `Report` model (section 4) must have a field for each of the 10 answers, and
`docs/evaluation.md` must report, per question, how often the system produced an answer
backed by a real source vs how often it had to say "insufficient evidence" — that
per-question completeness rate is a genuinely strong thing to put in the README.

## Competitor comparison — makes the numbers mean something

A number alone ("12% revenue growth") is not useful without context. The system must
identify 2–3 real competitors and compare the target against them on every numeric
checklist item. This directly strengthens Q7 (durable competitive advantage), which is
close to unanswerable without a peer baseline.

- **Manager** identifies competitors via a real search when setting scope — never guessed
  or hardcoded. Store them as part of `ResearchScope`.
- **Financial agent** fetches the same metrics (revenue growth, margins, ROE/ROCE, P/E,
  debt-to-equity) for each competitor, not just the target — same calls, looped.
- **Analyst** adds one comparison step per metric: is the target above, below, or in line
  with peers? This feeds the checklist answers directly (e.g. Q2's answer becomes "12% YoY,
  vs sector average 7%"), not a separate bolted-on section.
- **Report** gets a `peer_comparison` field: a table of target vs each competitor across
  the numeric metrics.

---

## 2. Non-goals

- Not a trading system. No buy/sell execution, ever.
- Not real-time monitoring. One-shot research per question.
- Not portfolio optimization or personalized financial advice.
- Not covering every market — start with large, well-covered public companies where
  fundamentals and news are reliably available.

---

## 3. Architecture

```
Investment question in (e.g. "Is Company X a reasonable investment right now?")
     |
[Manager]  -> sets scope: which company, what time window, what to prioritize
     |
     |-----------------+-----------------+
     v                 v                 v
[Financial]        [News]            [Risk]
  FMP fundamentals   Tavily search     computes from Financial's
  + Alpha Vantage     + article fetch   own price data (pure Python:
  price history                        std dev of returns, sector
     |                 |                concentration)
     v                 v                 v
     +-----------------+-----------------+
                        |
                   [Analyst]
                        |
          does the numeric story match the
          qualitative story? any contradiction?
                        |
              yes -> route a specific follow-up
                     back to ONE specialist
                     (max 2 rounds)
              no  -> write the report
                        |
                        v
                     [Report]
              (always ends with the
               disclaimer, hardcoded)
```

**Design decisions to implement and document:**

| Decision | Reason (put this in docs/architecture.md) |
|---|---|
| Three specialists run in parallel, not sequentially | They're independent until the cross-check — running sequentially only adds latency with no benefit |
| Risk agent has no separate API | Volatility and exposure are computable from price data the Financial agent already fetched. A separate "risk data" API would be redundant and add an unnecessary dependency |
| Analyst never just merges — it must find and act on contradictions | This is the entire point of the project. Without it, the system is three parallel LLM calls and a summary — the same thing one LLM with search could produce in a single pass |
| Max 2 follow-up rounds | Keeps cost and latency bounded; forces the analyst to reach a conclusion even with imperfect information, same as a real analyst working to a deadline |
| Disclaimer is a hardcoded template element, not an agent decision | Removes any chance an agent omits it under prompt pressure |
| No MCP | A deliberate simplification for a first project — direct API calls are easier to build, debug, and explain in an interview. Documented, not accidental |

---

## 4. Data models (`src/investpanel/models/`)

Pydantic v2. Agents may only exchange these.

```python
class ResearchScope(BaseModel):
    company: str
    ticker: str | None
    competitors: list[str]      # 2-3 real competitors, found via search, never guessed
    time_window: str            # e.g. "last 12 months"
    priority_focus: str | None  # set by the manager if the question implies one

class FinancialFinding(BaseModel):
    metric: str                 # one of: revenue_growth, profit_growth, operating_cash_flow,
                                 # debt_to_equity, interest_coverage, roce, roe, pe_ratio,
                                 # pb_ratio, valuation_vs_growth
    value: float
    unit: str
    period: str
    source: str                 # which API + endpoint, always present
    interpretation: str         # plain-English, one sentence
    healthy: bool                # is this metric in a healthy range — the yes/no the
                                 # checklist question actually needs

class NewsFinding(BaseModel):
    headline: str
    summary: str                # your own words, not copied text
    source_url: HttpUrl         # REQUIRED
    published_date: date
    relevance: Literal["high", "medium", "low"]
    checklist_question: Literal["moat", "management", "risk"] | None = None
                                 # tags which of Q7/Q8/Q9 this finding supports, if any

class RiskFinding(BaseModel):
    metric: str                 # e.g. "annualized_volatility"
    value: float
    computed_from: str          # e.g. "252-day price history, FMP+AlphaVantage"
    interpretation: str

class Contradiction(BaseModel):
    between: tuple[str, str]    # e.g. ("financial", "news")
    description: str
    follow_up_target: Literal["financial", "news", "risk"]
    follow_up_question: str

class Report(BaseModel):
    company: str
    company_description: str    # answers Q1, set once by the Manager
    summary: str
    checklist_answers: dict[str, str]
                                 # keys "q2".."q10", each a short answer + confidence,
                                 # or "insufficient evidence" — this is what
                                 # docs/evaluation.md reports completeness on
    peer_comparison: dict[str, dict[str, float]]
                                 # metric -> {company_name: value}, target + 2-3 competitors
    financial_findings: list[FinancialFinding]
    news_findings: list[NewsFinding]
    risk_findings: list[RiskFinding]
    contradictions_found: list[Contradiction]
    contradictions_resolved: int
    disclaimer: str = (
        "This is informational analysis only, not investment advice. "
        "It is not a recommendation to buy, sell, or hold any security. "
        "Consult a licensed financial advisor before making investment decisions."
    )
```

Validators to write and unit-test:

- `NewsFinding.source_url` required and must resolve to a real fetched page (enforced
  upstream by the tool layer, checked here at the schema level).
- `Report.disclaimer` cannot be overridden or removed by any agent — enforce with a
  `Field(frozen=True)` or equivalent, and test that no code path can produce a Report
  missing it.

---

## 5. Phased build plan

Stop at every **GATE**. Show the user the result. Do not proceed until they say continue.

### Phase 0 — Skeleton and environment
- Folder structure (section 8).
- `uv init`, pin Python 3.11+, `uv add` for dependencies. No pip, no requirements.txt.
- `llm/factory.py`: Gemini by default, swappable.
- `tools/fmp_client.py`, `tools/alphavantage_client.py`, `tools/search.py` (Tavily) — each
  with a disk cache wrapper, retries, and a clear error when a key is missing.
- `utils/tracing.py`: LangSmith optional, local JSON traces always. Missing key never
  breaks a run.
- **GATE 0:** Gemini responds; each of the three data clients returns one real response
  for a known company (e.g. a well-known large-cap); a trace file is written.

### Phase 1 — Ground truth (NO agents yet)
- `eval/datasets/heldout_questions.py`: 30–40 hand-built questions. For each: the company,
  a specific date framing ("as of Jan 2025, given what was publicly known then..."), and a
  brief note on what the "reasonable" read of the situation was at that time — not a
  stock-price prediction, a reasoning-quality benchmark. The user supplies company/topic
  ideas; you draft the file and ask them to review before finalizing.
- `eval/metrics.py`:
  - reasoning-quality score against the documented "reasonable read" (rubric-based,
    scored by an LLM judge with a fixed rubric, logged)
  - **contradiction catch rate** — how often the system identifies a genuine tension
    between findings that exists in a labeled subset of the question set
  - **confidently wrong rate** — firm conclusions that contradict the documented
    reasonable read
  - cost per question, latency per question
- **GATE 1:** metrics module unit-tested against a hand-made fixture with known scores.

### Phase 2 — Baseline
- `eval/baselines/single_llm_search.py`: one LLM, one search call, asked to research and
  conclude, no specialist split, no cross-check.
- Run over the full question set. Commit results.
- **GATE 2:** one row of the results table exists with real numbers.

### Phase 3 — Specialists
- `agents/financial.py`, `agents/news.py`, `agents/risk.py`, `tools/volatility.py`
  (pure Python, unit-tested with a fixture — no LLM call for the math itself).
- Each specialist's output validated against its schema, including the source requirement.
- **GATE 3:** for one company, print all three specialists' findings side by side with
  sources, unprompted by any question — just raw specialist output.

### Phase 4 — Manager and Analyst
- `agents/manager.py`, `agents/analyst.py`.
- The analyst's cross-check logic is the most important code in the project — it must
  compare specific claims (a number, a date, a direction of change) across findings, not
  just eyeball for "does this feel consistent." Implement as an explicit comparison step
  the LLM performs against structured fields, not free-text judgment alone.
- `graph/` — LangGraph wiring: manager -> 3 parallel specialists -> analyst -> (loop to
  one specialist, max 2 rounds) -> report.
- **GATE 4:** end-to-end run on 5 companies. At least one must be constructed (or found
  naturally) to contain a real contradiction, and the trace must show the analyst catching
  it and routing a follow-up.

### Phase 5 — Measure and improve
- Full eval run: baseline vs InvestPanel over the full question set.
- Error analysis: bucket every case where InvestPanel's reasoning-quality score was equal
  to or worse than baseline. Fix the largest bucket. Re-run, report before/after.
- One ablation: run the analyst's cross-check step with a different model provider than
  the specialists, report whether independence changes the contradiction catch rate.
- **GATE 5:** results table complete, error analysis with counts, one measured
  improvement, one ablation.

### Phase 6 — Ship it
- `app.py` — Streamlit: enter a company, watch the panel research it, see the three
  specialist findings, see any contradiction found and the follow-up, see the final
  report with the disclaimer prominently shown.
- **Observability tab in the Streamlit app.** A second tab that reads the local JSON trace
  files (not a live re-run) and shows aggregate numbers across every run so far: how often
  the analyst-to-specialist loop fired, how often the no-unsourced-facts validator
  rejected an agent's output, average cost and latency per company, per-question
  completeness rate across the 10 checklist questions. This turns the tracing data
  collected since Phase 0 into something visible, not just logged to disk.
- **Report export.** Every report the app generates must also be downloadable as a single
  static file (Markdown or PDF) with the same content — 10-question table, peer
  comparison, disclaimer — so the user can save or share one company's report outside the
  running app. This is separate from the observability tab, which summarizes many runs;
  report export is one run, saved.
- `Dockerfile`, `make demo`.
- Deploy to Streamlit Community Cloud, live link at the top of the README.
- `docs/architecture.md`, `docs/agent_contracts.md`, `docs/evaluation.md`,
  `docs/interview_notes.md`.
- **GATE 6:** a stranger can clone, add four API keys, and run it.

---

## 6. README requirements

1. One-line description, live demo link, screenshot or GIF.
2. **The disclaimer, prominently, near the top** — not buried in a footer.
3. Results table immediately after:

   | System | Reasoning quality | Contradiction catch rate | Confidently wrong | Cost/question | Latency |
   |---|---|---|---|---|---|
   | Single LLM + search | | | | | |
   | InvestPanel | | | | | |

4. "Why not just one AI?" — three sentences, plain English, centered on the cross-check.
5. Architecture diagram + one line per agent.
6. Quickstart: clone, install, four env vars, run.
7. **Limitations** — stated plainly. Reasoning-quality scoring uses an LLM judge, which
   has its own biases. Coverage is limited to large, well-documented companies. This is
   not predictive of future prices and should never be read as such.
8. What was learned / what would come next.

---

## 7. Testing requirements

- `tests/test_models.py` — validators, especially the disclaimer-cannot-be-removed rule.
- `tests/test_volatility.py` — fixture-based, no network, no LLM.
- `tests/test_agents.py` — mocked LLM and mocked API clients, including malformed JSON,
  missing source fields, and a deliberately contradictory input to confirm the analyst
  catches it.
- `tests/test_workflow.py` — loop terminates at 2 rounds; graceful degradation if a
  specialist fails.
- No test may make a real API call of any kind.

---

## 8. Full folder structure

```
investpanel/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── Makefile
├── run.py
├── app.py
├── docs/
│   ├── BUILD_SPEC.md
│   ├── architecture.md
│   ├── agent_contracts.md
│   ├── evaluation.md
│   └── interview_notes.md
├── src/investpanel/
│   ├── __init__.py
│   ├── config.py
│   ├── models/
│   │   ├── scope.py
│   │   ├── findings.py
│   │   ├── contradiction.py
│   │   └── report.py
│   ├── agents/
│   │   ├── base.py
│   │   ├── manager.py
│   │   ├── financial.py
│   │   ├── news.py
│   │   ├── risk.py
│   │   └── analyst.py
│   ├── tools/
│   │   ├── fmp_client.py
│   │   ├── alphavantage_client.py
│   │   ├── search.py
│   │   ├── fetch.py
│   │   ├── cache.py
│   │   └── volatility.py
│   ├── graph/
│   │   ├── state.py
│   │   ├── workflow.py
│   │   └── routing.py
│   ├── llm/
│   │   ├── factory.py
│   │   └── usage.py
│   └── utils/
│       ├── logging.py
│       └── tracing.py
├── eval/
│   ├── datasets/
│   │   └── heldout_questions.py
│   ├── baselines/
│   │   └── single_llm_search.py
│   ├── metrics.py
│   ├── run_eval.py
│   └── results/
├── data/
│   ├── heldout_questions.json
│   └── cache/
└── tests/
    ├── test_models.py
    ├── test_volatility.py
    ├── test_agents.py
    └── test_workflow.py
```

---

## 9. Interview defence pack

At the end of the build, produce `docs/interview_notes.md` answering, in plain English:

1. Why can't a single LLM do this?
2. Why does the risk agent not have its own API — where does its data come from?
3. What exactly does the analyst agent's cross-check compare, mechanically?
4. Why is the report disclaimer hardcoded rather than left to an agent?
5. What does "confidently wrong" mean here and why is it a headline metric?
6. What is the biggest failure mode of this system?
7. Why was MCP deliberately not used, and what would change if it were added?
8. What would you do next with three more months?

---

## 10. First action

Read this whole document and `CLAUDE.md`. Then create the folder structure and Phase 0
files, explain each one in plain English, and stop at GATE 0.

---

# Amendment A — Phase 7 upgrade (supersedes the sections it names)

The original spec above describes the system as first built. This amendment records
five changes made afterwards. Where the two disagree, this amendment wins.

## A1. Dynamic routing (new: Query Analyzer)

The original design always ran Financial + News + Risk. That is wasteful for a
question like "what is Nike's P/E?" and it dilutes the report with sections nobody
asked for.

A **Query Analyzer** runs before the Manager and classifies the question into one
`QueryIntent`: `quick_fact`, `financial_health`, `risk_only`, `news_only`,
`competitor_comparison`, or `full_due_diligence`. The intent maps to a set of
specialists via a **Python table**, not via LLM output — the model chooses one label
and nothing more, because routing is control flow and must not depend on the model
returning a well-formed combination of booleans.

Rules:
- Any classification failure falls back to `full_due_diligence`. Running too much is
  a cost problem; running too little is a correctness problem.
- The follow-up loop may never wake a specialist the plan skipped.
- A skipped agent is reported as **"Not requested"**, never "Insufficient evidence" —
  a routing decision must not be presented to the reader as a data failure.

## A2. All numeric work is deterministic Python

Restates and tightens hard rule "never fabricate a number".

- Every ratio, growth rate, margin and valuation figure is computed by an explicit
  Python function over raw API fields. The LLM interprets numbers; it never produces
  them.
- Metrics: revenue/profit growth, **gross/operating/net margin**, operating cash flow,
  **cash conversion (OCF ÷ net income)**, debt-to-equity, interest coverage, ROCE, ROE,
  P/E, P/B, PEG-like, annualized volatility, max drawdown.
- **Enforcement, not instruction:** `utils/numeric_guard.py` extracts every figure from
  any LLM-generated prose and checks it against the computed findings. A summary
  containing an unsupported number is discarded in favour of a counted template.
  It tolerates honest rounding (0.2091 → "20.9%") and rejects fabrication.
- Scalar math stays plain Python rather than Pandas: a DataFrame around a single
  division adds indirection without adding determinism, and the project's style rule
  is code the maintainer can read line by line.

## A3. Critic step (new agent)

Supersedes "the analyst cross-checks". The cross-check is now a **separate node**
between the specialists and the Analyst.

- `CriticAgent.review()` returns three separate things: **confirmed contradictions**
  (which earn a follow-up round), **potential tensions** (worth attention, never
  trigger the loop), and **additional findings** (see A5).
- The Critic drives the bounded follow-up loop. `MAX_FOLLOWUP_ROUNDS = 2` is unchanged.
- The Analyst receives the Critic's output as input it **must address**; its prompt
  says so explicitly. Splitting the roles matters because synthesis naturally pulls
  toward a tidy story, and a tidy story is where contradictions go to die.

## A4. Competitor comparison (completed)

The comparison existed; two things were missing.

- Competitor tickers came straight from the LLM and were never verified, so
  unresolvable symbols silently vanished from the table. Every candidate now goes
  through the same `resolve_ticker` verification as the target, duplicates are
  dropped, and the count is capped by `config.MAX_COMPETITORS`.
- The table gained a **"vs peers"** column comparing the target to the peer average,
  with direction interpreted per metric — being *below* the peer average on debt or
  P/E is favourable, not a shortfall.
- Known limitation: the FMP free plan returns 402 for many non-US peers, so those
  comparisons show "no peer data" with a stated reason.

## A5. The checklist is a floor, not a ceiling

Supersedes any reading of section 4 that treats the 10 questions as the maximum scope.

The checklist is the **minimum** every report must cover. Agents may surface any
additional financially material finding, carried as an `Observation` (source, title,
detail, severity, **evidence**). Detectors are deterministic and each cites the
numbers it fired on: margin consumed before the bottom line, operating losses, profit
not converting to cash, growth-priced valuation without growth, thin interest cover,
drawdown deeper than volatility implies, and sourced news that no checklist question
covers.

An LLM is deliberately *not* asked to "find anything else interesting" — that produces
confident commentary with no evidence behind it, which is the failure mode this
project exists to avoid.

## A6. Explicitly out of scope

Not added, and not to be added without a new decision: RAG / vector databases,
SEC EDGAR integration, DCF or scenario modelling, and a management/governance agent.
