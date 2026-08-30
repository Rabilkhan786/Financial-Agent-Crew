"""Tests for the FastAPI service.

The crew is stubbed out throughout - these check the HTTP layer (status codes,
JSON shape, the streaming protocol, the path guards), not the agents, which
have their own tests. That keeps them offline, fast, and runnable without a
GROQ_API_KEY.
"""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
from src import graph


@pytest.fixture
def client():
    return TestClient(api.app)


def fake_state(report="## Executive summary\nAll good."):
    """A crew state shaped like a real one, including the pandas bits."""
    return {
        "ticker": "TEST",
        "company": "Test Company",
        "report": report,
        "revision_count": 0,
        "max_revisions": 2,
        "errors": [],
        "conversation_log": [{"agent": "orchestrator", "message": "started"},
                             {"agent": "report_writer", "message": "wrote it"}],
        "fundamentals": {
            "available": True,
            "metrics": {"operating_margin": 0.207, "net_margin": float("nan")},
            "series": {"revenue": pd.Series([1.0, 2.0], index=["2023", "2024"])},
        },
        "analysis": {
            "available": True,
            "kpis": {"total_return": 0.15},
            "charts": {"price": "output/TEST_price.png"},
        },
    }


# --- health -----------------------------------------------------------------

def test_health_reports_the_model_and_the_sources(client):
    body = client.get("/health").json()
    assert body["status"] in ("ok", "not configured")
    assert "model" in body
    assert isinstance(body["sources"], dict)


# --- /analyse ---------------------------------------------------------------

def test_analyse_returns_a_json_safe_result(monkeypatch, client):
    monkeypatch.setattr(graph, "run_crew", lambda *a, **k: fake_state())
    monkeypatch.setattr(api.report_pdf, "build_pdf", lambda state: "output/TEST_report.pdf")

    response = client.post("/analyse", json={"ticker": "TEST",
                                             "start_date": "2023-01-01",
                                             "end_date": "2024-01-01"})
    assert response.status_code == 200
    body = response.json()

    assert body["ticker"] == "TEST"
    assert body["report"].startswith("## Executive summary")
    # The NaN must have become null, not a bare NaN token that no browser
    # could parse - checked on the raw text, not the parsed body.
    assert "NaN" not in response.text
    assert body["fundamentals"]["metrics"]["net_margin"] is None
    # The pandas Series arrived as records.
    assert body["fundamentals"]["series"]["revenue"][0]["period"] == "2023"


def test_analyse_turns_chart_paths_into_urls(monkeypatch, client):
    monkeypatch.setattr(graph, "run_crew", lambda *a, **k: fake_state())
    monkeypatch.setattr(api.report_pdf, "build_pdf", lambda state: "output/TEST_report.pdf")

    body = client.post("/analyse", json={"ticker": "TEST", "start_date": "2023-01-01",
                                         "end_date": "2024-01-01"}).json()
    # A path on the API server's disk means nothing to a remote client.
    assert body["analysis"]["charts"]["price"] == "/charts/TEST_price.png"
    assert body["pdf_url"] == "/report/TEST/pdf"


def test_analyse_reports_a_crew_failure_as_a_500(monkeypatch, client):
    def boom(*args, **kwargs):
        raise RuntimeError("the provider is down")

    monkeypatch.setattr(graph, "run_crew", boom)
    response = client.post("/analyse", json={"ticker": "TEST", "start_date": "2023-01-01",
                                             "end_date": "2024-01-01"})
    assert response.status_code == 500
    assert "the provider is down" in response.json()["detail"]


def test_a_run_with_no_report_has_no_pdf_url(monkeypatch, client):
    monkeypatch.setattr(graph, "run_crew", lambda *a, **k: fake_state(report=""))
    body = client.post("/analyse", json={"ticker": "TEST", "start_date": "2023-01-01",
                                         "end_date": "2024-01-01"}).json()
    assert body["pdf_url"] is None


# --- /analyse/stream --------------------------------------------------------

def events_from(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_stream_sends_progress_then_one_result(monkeypatch, client):
    state = fake_state()

    def fake_stream(*args, **kwargs):
        # Two snapshots, the log growing between them, as LangGraph does it.
        yield {**state, "conversation_log": state["conversation_log"][:1]}
        yield state

    monkeypatch.setattr(graph, "stream_crew", fake_stream)
    monkeypatch.setattr(api.report_pdf, "build_pdf", lambda s: "output/TEST_report.pdf")

    events = events_from(client.post("/analyse/stream",
                                     json={"ticker": "TEST", "start_date": "2023-01-01",
                                           "end_date": "2024-01-01"}))
    kinds = [event["event"] for event in events]
    assert kinds == ["progress", "progress", "result"]
    # Each log entry is announced exactly once, not re-sent every snapshot.
    assert [event["agent"] for event in events[:2]] == ["orchestrator", "report_writer"]
    assert events[-1]["result"]["ticker"] == "TEST"


def test_stream_sends_an_error_event_rather_than_dying_silently(monkeypatch, client):
    def boom(*args, **kwargs):
        raise RuntimeError("provider exploded")
        yield  # pragma: no cover - makes this a generator

    monkeypatch.setattr(graph, "stream_crew", boom)
    events = events_from(client.post("/analyse/stream",
                                     json={"ticker": "TEST", "start_date": "2023-01-01",
                                           "end_date": "2024-01-01"}))
    assert events[-1]["event"] == "error"
    assert "provider exploded" in events[-1]["detail"]


def test_a_stream_that_yields_nothing_is_an_error_not_a_success(monkeypatch, client):
    def nothing(*args, **kwargs):
        return
        yield  # pragma: no cover - makes this a generator

    monkeypatch.setattr(graph, "stream_crew", nothing)
    events = events_from(client.post("/analyse/stream",
                                     json={"ticker": "TEST", "start_date": "2023-01-01",
                                           "end_date": "2024-01-01"}))
    assert events[-1]["event"] == "error"


# --- the file-serving endpoints and their guards ---------------------------

def test_a_missing_chart_is_a_404(client):
    assert client.get("/charts/does_not_exist.png").status_code == 404


def test_a_chart_name_with_a_path_in_it_is_refused(client):
    # Not a real traversal attempt against this app, but the endpoint takes a
    # name from a URL and joins it to a folder, so it refuses anything that is
    # not a bare filename rather than resolving it.
    assert client.get("/charts/..%2F..%2Fsecret.txt").status_code in (400, 404)


def test_a_missing_report_is_a_404(client):
    assert client.get("/report/NOSUCHTICKER/pdf").status_code == 404
