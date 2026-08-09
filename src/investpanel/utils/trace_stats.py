"""Aggregate the local JSON traces into headline numbers for the app.

The Streamlit observability tab shows how the panel has behaved across every run
so far — how often the analyst's follow-up loop fired, average latency, average
checklist completeness — by reading the "panel_run" trace files written on each
run. This module is the pure aggregation step, kept separate from the UI so it can
be unit-tested with fixture files and no Streamlit involved.
"""

import json
from pathlib import Path


def _load_panel_runs(trace_dir: Path) -> list[dict]:
    """Read every panel_run trace file in the directory into a list of dicts."""
    runs = []
    if not trace_dir.exists():
        return runs
    for path in sorted(trace_dir.glob("*_panel_run.json")):
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            # A corrupt trace file shouldn't break the dashboard; just skip it.
            continue
    return runs


def summarize_panel_runs(trace_dir: Path) -> dict:
    """Return aggregate stats across all recorded panel runs.

    Returns zeros (not an error) when there are no runs yet, so the dashboard can
    render cleanly before the panel has ever been run.
    """
    runs = _load_panel_runs(trace_dir)
    n = len(runs)
    if n == 0:
        return {
            "num_runs": 0,
            "loop_fire_rate": 0.0,
            "avg_latency_seconds": 0.0,
            "avg_checklist_completeness": 0.0,
            "avg_contradictions_found": 0.0,
            "runs": [],
        }

    loops = sum(1 for r in runs if r.get("loop_fired"))
    return {
        "num_runs": n,
        "loop_fire_rate": round(loops / n, 3),
        "avg_latency_seconds": round(sum(r.get("latency_seconds", 0) for r in runs) / n, 3),
        "avg_checklist_completeness": round(
            sum(r.get("checklist_completeness", 0) for r in runs) / n, 3
        ),
        "avg_contradictions_found": round(
            sum(r.get("contradictions_found", 0) for r in runs) / n, 3
        ),
        "runs": runs,
    }
