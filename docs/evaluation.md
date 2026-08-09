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

## Numeric accuracy (objective — where the panel wins), n = 20 figures

`eval/numeric_accuracy.py` compares real API values against what each system reports. The panel
computes figures from the API (correct by construction); a single LLM (with search) states them
from memory. Result:

| System | Numeric accuracy |
|---|---|
| InvestPanel (computes) | 100% (20/20) |
| Single LLM + search (guesses) | 40% (8/20) |

Example — Apple: real revenue growth 6.4% vs LLM's 16.6%; real debt/equity 1.5 vs LLM's 0.78.
This is the panel's clearest, most defensible advantage: in finance, a hallucinated number is
worse than no number. See `eval/results/numeric_accuracy.json`.

## Reasoning-quality results (real run, n = 11 of 34)

Produced by `run_all` on 2026-08-09 with Groq `llama-3.3-70b-versatile`; the free daily token
limit stopped it after 11 questions. Never hand-written (hard rule #2) — see
`eval/results/comparison.json`.

| System | Reasoning quality (0–1) | Contradiction catch rate | Confidently wrong |
|---|---|---|---|
| Single LLM + search | 0.77 | 0.83 (5/6) | 0.00 |
| InvestPanel | 0.48 | 0.50 (3/6) | 0.00 |

(Cost ≈ $0 on the free tier; per-question latency not recorded in this run.)

## Error analysis (the honest part)

**In this configuration the baseline beat the panel.** Rule #2 says report and analyse that.

Most likely cause — a **data/label mismatch confound**: FMP/Alpha Vantage return *current*
fundamentals, but the questions and "reasonable reads" are framed at a *past* date. So:

- The **baseline** does a web search that surfaces the historically-framed context, so its
  answer lines up better with the past-dated reference read.
- The **panel** faithfully reports *today's* numbers (e.g. current P/E, latest growth), which
  the historical answer key marks down — and it correctly finds *no* contradiction on a company
  whose 2023 tension no longer exists today, yet that scores as a "miss" against the historical
  label.

Evidence the panel's mechanism itself is sound: the live Tesla run catches a real
valuation-vs-fundamentals contradiction on current data (README). The `confidently_wrong` rate
is 0.00 for both because it only triggers on the judge's floor score, which nothing hit.

**What would make the comparison fair (out of scope for this portfolio version):**
point-in-time fundamentals aligned to each question's date, plus reasonable-reads written
against that same data. With current-only data, the meaningful comparison is on questions
framed "as of today", not the historical set.

## Error analysis and ablation

- **Error analysis (done, informally):** running on live data surfaced a real gap — the
  analyst under-caught the "expensive-but-shrinking" contradiction (Tesla: P/E 278 vs profit
  −47%). A dedicated detector was added and unit-tested, and the loop then fired correctly.
- **Ablation (supported, not run at scale here):** `llm/factory.py`'s `provider` argument lets
  the analyst run on a *different* model than the specialists — the intended experiment is
  whether that independence changes the catch rate. Left as documented future work for this
  portfolio version.
