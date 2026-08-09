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


def print_report(report: Report) -> None:
    print(f"\n{'=' * 70}\n  {report.company}\n{'=' * 70}\n")
    print(f"What it does (Q1): {report.company_description}\n")
    print(f"Summary: {report.summary}\n")

    print("10-question checklist:")
    print(f"  q1: {report.company_description[:80]}...")
    for key in [f"q{i}" for i in range(2, 11)]:
        print(f"  {key}: {report.checklist_answers.get(key, 'insufficient evidence')}")

    if report.peer_comparison:
        print("\nPeer comparison (metric -> {company: value}):")
        for metric, values in report.peer_comparison.items():
            print(f"  {metric}: {values}")

    print(f"\nContradictions found: {len(report.contradictions_found)} "
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
