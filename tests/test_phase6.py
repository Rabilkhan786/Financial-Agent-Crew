"""Tests for the Phase 6 pure helpers: markdown export and trace aggregation.

No Streamlit, no network — just the logic behind the app.
"""

import json

from investpanel.models.contradiction import Contradiction
from investpanel.models.report import DISCLAIMER_TEXT, Report
from investpanel.utils.report_export import report_to_markdown
from investpanel.utils.trace_stats import summarize_panel_runs


def _report():
    return Report(
        company="Acme",
        company_description="Acme makes widgets.",
        summary="A balanced summary.",
        checklist_answers={"q2": "revenue up (healthy)", "q7": "insufficient evidence"},
        peer_comparison={"revenue_growth": {"ACME": 12.0, "RIVL": 7.0}},
        contradictions_found=[
            Contradiction(
                between=("financial", "news"),
                description="numbers vs narrative",
                follow_up_target="financial",
                follow_up_question="look again",
            )
        ],
        contradictions_resolved=1,
    )


def test_markdown_export_has_key_sections_and_ends_with_disclaimer():
    md = report_to_markdown(_report())
    assert "# InvestPanel report — Acme" in md
    assert "Acme makes widgets." in md
    assert "10-question checklist" in md
    assert "Peer comparison" in md
    assert "numbers vs narrative" in md
    # The disclaimer must be present, at the very end.
    assert md.rstrip().endswith(f"_{DISCLAIMER_TEXT}_")


def test_summarize_panel_runs_empty_dir(tmp_path):
    stats = summarize_panel_runs(tmp_path)
    assert stats["num_runs"] == 0
    assert stats["loop_fire_rate"] == 0.0


def test_summarize_panel_runs_aggregates(tmp_path):
    runs = [
        {"loop_fired": True, "latency_seconds": 10.0, "checklist_completeness": 1.0,
         "contradictions_found": 2},
        {"loop_fired": False, "latency_seconds": 20.0, "checklist_completeness": 0.5,
         "contradictions_found": 0},
    ]
    for i, run in enumerate(runs):
        (tmp_path / f"2026010{i}_panel_run.json").write_text(json.dumps(run), encoding="utf-8")

    stats = summarize_panel_runs(tmp_path)
    assert stats["num_runs"] == 2
    assert stats["loop_fire_rate"] == 0.5           # 1 of 2 fired
    assert stats["avg_latency_seconds"] == 15.0     # (10 + 20) / 2
    assert stats["avg_checklist_completeness"] == 0.75
    assert stats["avg_contradictions_found"] == 1.0
