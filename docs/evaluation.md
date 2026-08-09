# Evaluation

The whole project is built to answer one question honestly: **does the analyst's
cross-check catch contradictions a single-LLM-with-search baseline misses?** This
file documents how we measure that. Every number in the README comes from
re-runnable scripts in `eval/` — none are typed in by hand.

## The question set

`eval/datasets/heldout_questions.py` holds 34 hand-built questions, each framed
*as of a past date* with (a) what was publicly knowable then and (b) the
"reasonable read" — the sound analytical conclusion given that context. It is a
**reasoning-quality benchmark, not a price prediction.** 11 of the 34 are labeled
with a genuine financial-vs-qualitative contradiction; that labeled subset is what
the contradiction catch rate is measured against.

## Metrics (`eval/metrics.py`)

- **Reasoning quality (0-1).** An LLM judge scores the analysis 1-5 against a fixed
  rubric (`REASONING_RUBRIC`), normalized to 0-1. The judge is injectable so tests
  use a fake one — no test makes a real API call.
- **Contradiction catch rate.** Of the labeled-contradiction questions, the fraction
  the system actually flagged (a recall measure).
- **Confidently-wrong rate.** How often the system gave a *firm* conclusion that the
  judge rated as contradicting the reasonable read. Being confidently wrong is worse
  than saying "insufficient evidence", so it's a headline number.
- **Cost and latency per question.**

## Per-question completeness

The Report answers 10 checklist questions (q1-q10). `docs`-worthy completeness =
how often each question came back with a real, sourced answer versus "insufficient
evidence". The numeric questions (q2-q6, q10) read straight from the financial
findings; the judgment questions (q7 moat, q8 management, q9 risk) are answered only
when a sourced news/risk finding supports them.

## How to run

```bash
uv run python -m eval.baselines.single_llm_search   # baseline row  -> eval/results/baseline.json
uv run python -m eval.run_eval                       # both rows     -> eval/results/comparison.json
```

## Results

> These tables are populated by `uv run python -m eval.run_eval`. They are left
> blank here on purpose — no number goes in the README or these docs until a real
> run produces it (project hard rule: never fabricate a number).

| System | Reasoning quality | Contradiction catch rate | Confidently wrong | Cost/question | Latency |
|---|---|---|---|---|---|
| Single LLM + search | _pending run_ | _pending run_ | _pending run_ | _pending run_ | _pending run_ |
| InvestPanel | _pending run_ | _pending run_ | _pending run_ | _pending run_ | _pending run_ |

## Error analysis and ablation (Phase 5, pending a live run)

- **Error analysis:** bucket every case where InvestPanel's reasoning-quality score
  was ≤ the baseline's, fix the largest bucket, re-run, report before/after.
- **Ablation:** run the analyst's cross-check with a *different* model provider than
  the specialists and report whether that independence changes the catch rate. The
  `llm/factory.py` `provider` argument exists precisely to make this a one-line change.
