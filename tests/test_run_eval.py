"""Test the one bit of eval logic worth testing without a live run:
turning a panel Report into the scorer's (conclusion, flagged, firm) inputs.
"""

from eval.run_eval import report_to_answer
from investpanel.models.contradiction import Contradiction
from investpanel.models.report import Report


def _report(checklist, contradictions=None):
    return Report(
        company="Acme",
        company_description="Widgets.",
        summary="A balanced summary.",
        checklist_answers=checklist,
        contradictions_found=contradictions or [],
    )


def test_firm_when_most_questions_answered():
    checklist = {f"q{i}": "revenue up (healthy)" for i in range(2, 11)}  # all answered
    conclusion, flagged, firm = report_to_answer(_report(checklist))
    assert conclusion == "A balanced summary."
    assert firm is True
    assert flagged is False


def test_not_firm_when_mostly_insufficient():
    checklist = {f"q{i}": "insufficient evidence" for i in range(2, 11)}
    _, _, firm = report_to_answer(_report(checklist))
    assert firm is False


def test_flagged_when_contradiction_present():
    checklist = {f"q{i}": "answered" for i in range(2, 11)}
    contradiction = Contradiction(
        between=("financial", "news"),
        description="d",
        follow_up_target="news",
        follow_up_question="q",
    )
    _, flagged, _ = report_to_answer(_report(checklist, [contradiction]))
    assert flagged is True
