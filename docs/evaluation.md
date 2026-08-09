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
uv run python -m eval.run_eval                       # full 34, both rows -> eval/results/comparison.json
# run_all(questions=...) also takes a subset for a quick representative sample
```

## Important caveats (read before trusting the numbers)

Being a **portfolio** project, the eval is honest about its limits:

1. **The data is current, not point-in-time.** FMP/Alpha Vantage return the *latest*
   fundamentals, while the questions are framed historically. So this measures the two
   systems **on the same current data** — a fair *systems comparison* (does the panel catch
   contradictions the baseline misses?), **not** a rigorous historical backtest. A real
   backtest would need point-in-time data.
2. **The judge is an LLM** with its own biases; scores are indicative, not ground truth.
3. **Reported numbers are from a representative sample**, not the full 34 (running the full
   set on a free model is slow; the harness supports it — see above).

## Results (representative sample)

Populated from an actual run of `run_all` on a sample of the question set (never
hand-written — project hard rule #2). See `eval/results/comparison_sample.json`.

| System | Reasoning quality | Contradiction catch rate | Confidently wrong | Cost/question | Latency |
|---|---|---|---|---|---|
| Single LLM + search | _filled from sample run_ | | | | |
| InvestPanel | _filled from sample run_ | | | | |

The headline comparison to look at is **contradiction catch rate**: the panel's reason for
existing is catching tensions the single-pass baseline glosses over (demonstrated live on
Tesla — see the README).

## Error analysis and ablation

- **Error analysis (done, informally):** running on live data surfaced a real gap — the
  analyst under-caught the "expensive-but-shrinking" contradiction (Tesla: P/E 278 vs profit
  −47%). A dedicated detector was added and unit-tested, and the loop then fired correctly.
- **Ablation (supported, not run at scale here):** `llm/factory.py`'s `provider` argument lets
  the analyst run on a *different* model than the specialists — the intended experiment is
  whether that independence changes the catch rate. Left as documented future work for this
  portfolio version.
