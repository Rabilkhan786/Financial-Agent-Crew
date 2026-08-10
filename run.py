"""Command-line entry point: research one company with the full panel.

    uv run python run.py "Is Apple a reasonable long-term investment?"

It runs the whole graph (manager -> specialists -> analyst -> follow-up loop ->
report) and prints the report in plain text, including any contradiction the
analyst caught and how many follow-ups it ran — which is exactly the evidence
GATE 4 asks for. Needs all four API keys in .env.
"""

import sys

from investpanel.graph.workflow import run_panel
from investpanel.models.report import Report
from investpanel.utils.report_analysis import (
    build_executive_summary,
    build_human_checklist,
    data_freshness,
    evidence_quality,
    question_was_rewritten,
)

# Force UTF-8 console output so special characters in headlines/summaries don't
# crash printing on Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def print_report(report: Report) -> None:
    header = report.company + (f" ({report.ticker})" if report.ticker else "")
    print(f"\n{'=' * 70}\n  {header}\n{'=' * 70}\n")

    if question_was_rewritten(report):
        print(f'Interpreted your question as: "{report.interpreted_question}"\n')

    freshness = data_freshness(report)
    for label, value in freshness.items():
        print(f"{label}: {value}")
    quality = evidence_quality(report, report.ticker)
    print(f"Evidence quality: {quality['Overall']}\n")

    print("Executive Summary:")
    for category, rating in build_executive_summary(report).items():
        print(f"  {category}: {rating}")
    print(f"\nKey Takeaway: {report.summary}\n")

    print(f"What it does (Q1): {report.company_description}\n")

    print("10-question checklist:")
    for row in build_human_checklist(report):
        print(f"  [{row['status']}] {row['question']} -> {row['result']}")

    if report.peer_comparison:
        print("\nPeer comparison (metric -> {company: value}):")
        for metric, values in report.peer_comparison.items():
            print(f"  {metric}: {values}")

    if report.potential_tensions:
        print(f"\nPotential tensions: {len(report.potential_tensions)}")
        for t in report.potential_tensions:
            print(f"  - {t.between[0]} vs {t.between[1]}: {t.description}")

    print(f"\nConfirmed contradictions: {len(report.contradictions_found)} "
          f"(follow-ups run: {report.contradictions_resolved})")
    for c in report.contradictions_found:
        print(f"  - {c.between[0]} vs {c.between[1]}: {c.description}")
        print(f"      -> asked {c.follow_up_target}: {c.follow_up_question}")

    print(f"\nFindings: {len(report.financial_findings)} financial, "
          f"{len(report.news_findings)} news, {len(report.risk_findings)} risk.")

    # The disclaimer is always present and always this exact text — by construction.
    print(f"\n{'-' * 70}\n{report.disclaimer}\n{'-' * 70}\n")


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: uv run python run.py "Is <Company> a reasonable investment?"')
        raise SystemExit(1)
    question = sys.argv[1]
    print(f"Researching: {question}")
    report = run_panel(question)
    print_report(report)


if __name__ == "__main__":
    main()
