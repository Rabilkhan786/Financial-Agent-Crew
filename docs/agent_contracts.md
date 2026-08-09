# Agent contracts

Agents never pass free-form strings to each other — only the Pydantic models in
`src/investpanel/models/`. That makes every boundary explicit, validated, and
testable. This file is the reference for what each agent takes in and hands back.

## The shared models

- **`ResearchScope`** — company, ticker, 2-3 competitors (found via a real search),
  time window, optional priority focus.
- **`FinancialFinding`** — one numeric metric (from a fixed list), its value, unit,
  period, `source` (always present), a one-line interpretation, and a `healthy`
  yes/no. Every checklist numeric question maps to one of these.
- **`NewsFinding`** — headline, own-words summary, `source_url` (**required** — a
  NewsFinding cannot be built without a real URL), published date, relevance, and
  an optional tag for which judgment question (moat / management / risk) it supports.
- **`RiskFinding`** — metric, value, `computed_from` (which data produced it),
  interpretation.
- **`Contradiction`** — which two specialists disagree, a description, and a single
  `follow_up_target` + `follow_up_question`.
- **`Report`** — company, description (Q1), summary, the 10-question checklist
  answers, peer comparison, all findings, contradictions found + resolved, and the
  **frozen disclaimer** that no agent can change or remove.

## Per-agent input → output

| Agent | Input | Output | Notes |
|---|---|---|---|
| **Manager** | the question (str) | `ResearchScope` (+ company description from FMP) | Competitors come from a real search, never guessed. |
| **Financial** | ticker | `list[FinancialFinding]` (+ peer table) | Numbers computed in Python from FMP; the LLM writes no numbers. |
| **News** | company name (+ optional follow-up focus) | `list[NewsFinding]` | Summarizes only really-fetched articles; unfetchable or undated ones are skipped. |
| **Risk** | ticker | `list[RiskFinding]` | Volatility + drawdown from Alpha Vantage prices, pure Python, no LLM. |
| **Analyst** | all three finding lists | `list[Contradiction]`, then a `Report` | The cross-check is explicit detectors over structured fields; it routes one follow-up to one specialist, max twice. |

## Enforced rules

- **No unsourced facts.** `NewsFinding.source_url` is required by the schema;
  `FinancialFinding.source` and `RiskFinding.computed_from` are always populated by
  the code that builds them. Tested in `tests/test_models.py` and `tests/test_agents.py`.
- **The disclaimer cannot be removed.** A validator forces `Report.disclaimer` back
  to the canonical text and the field is frozen. Tested in `tests/test_models.py`.
- **The follow-up loop is bounded.** `config.MAX_FOLLOWUP_ROUNDS` caps it at 2.
  Tested in `tests/test_workflow.py`.
