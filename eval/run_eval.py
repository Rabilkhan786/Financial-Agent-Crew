"""Run the whole evaluation: baseline vs InvestPanel over the question set.

This is the script that produces the README results table — with real numbers,
never made-up ones. It scores both systems with the exact same metrics and judge,
writes the comparison to eval/results/comparison.json, and prints the two rows.

Needs all four API keys plus (for the reasoning-quality judge) Gemini. It is not
run by the test suite; the piece with logic worth testing — turning a panel Report
into the scorer's inputs — is unit-tested separately.
"""

import json
from pathlib import Path

from investpanel import config
from investpanel.models.report import Report


def report_to_answer(report: Report) -> tuple[str, bool, bool]:
    """Turn a panel Report into (conclusion, flagged_contradiction, firm_conclusion).

    So the panel can be scored by the same build_question_result the baseline uses.
    "firm" means at least half the checklist questions came back with a real answer
    rather than "insufficient evidence" — a simple, honest proxy for confidence.
    """
    conclusion = report.summary
    flagged = len(report.contradictions_found) > 0
    answered = [
        v for v in report.checklist_answers.values()
        if v and "insufficient evidence" not in v.lower()
    ]
    total = len(report.checklist_answers) or 1
    firm = (len(answered) / total) >= 0.5
    return conclusion, flagged, firm


def run_all(out_path: Path | None = None, questions=None):
    """Score both systems over the question set and write the comparison.

    ``questions`` defaults to the full held-out set; pass a subset (e.g. for a
    quick representative run) to score just those.
    """
    from eval.baselines.single_llm_search import run_baseline
    from eval.datasets.heldout_questions import QUESTIONS
    from eval.metrics import build_question_result, make_llm_judge, summarize
    from investpanel.graph.workflow import run_panel
    from investpanel.llm.factory import get_llm

    questions = questions if questions is not None else QUESTIONS
    out_path = out_path or (config.PROJECT_ROOT / "eval" / "results" / "comparison.json")
    judge = make_llm_judge(get_llm())

    def result_from(q, conclusion, flagged, firm):
        return build_question_result(
            question_id=q.id,
            question_text=q.question,
            reasonable_read=q.reasonable_read,
            had_known_contradiction=q.has_known_contradiction,
            conclusion=conclusion,
            flagged_contradiction=flagged,
            firm_conclusion=firm,
            judge=judge,
        )

    baseline_results = []
    panel_results = []
    for q in questions:
        # One question failing (e.g. a transient free-tier rate limit) must not
        # abandon the whole eval — skip it and keep going.
        try:
            ans = run_baseline(q)
            baseline_results.append(
                result_from(q, ans.conclusion, ans.flagged_contradiction, ans.firm_conclusion)
            )
            report = run_panel(q.question)
            conclusion, flagged, firm = report_to_answer(report)
            panel_results.append(result_from(q, conclusion, flagged, firm))
            print(f"  scored {q.id}")
        except Exception as error:  # noqa: BLE001 - skip a failed question, keep the eval going
            print(f"  SKIPPED {q.id}: {error}")

    baseline_summary = summarize("Single LLM + search", baseline_results)
    panel_summary = summarize("InvestPanel", panel_results)

    comparison = {"baseline": baseline_summary.as_dict(), "investpanel": panel_summary.as_dict()}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    print(f"\nWrote comparison to {out_path}\n")
    print(json.dumps(comparison, indent=2))
    return comparison


def main() -> None:
    run_all()


if __name__ == "__main__":
    main()
