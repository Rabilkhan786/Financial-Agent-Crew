"""Tests for the FastAPI service.

The crew is stubbed out throughout. These tests cover the HTTP layer rather
than the agent logic, so they stay fast and offline.
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
    """Return a small crew state shaped like a real result."""
    return {
        "ticker": "TEST",
        "company": "Test Company",
        "report": report,
        "revision_count": 0,
        "max_revisions": 2,
        "errors": [],
        "conversation_log": [
            {"agent": "orchestrator", "message": "started"},
            {"agent": "report_writer", "message": "wrote it"},
        ],
        "fundamentals": {
            "available": True,
            "metrics": {
                "operating_margin": 0.207,
                "net_margin": float("nan"),
            },
            "series": {
                "revenue": pd.Series([1.0, 2.0], index=["2023", "2024"])
            },
        },
        "analysis": {
            "available": True,
            "kpis": {"total_return": 0.15},
            "charts": {"price": "output/TEST_price.png"},
        },
    }


def test_health_reports_the_model_and_the_sources(client):
    body = client.get("/health").json()
    assert body["status"] in ("ok", "not configured")
    assert "model" in body
    assert isinstance(body["sources"], dict)


def test_analyse_returns_a_json_safe_result(monkeypatch, client):
    monkeypatch.setattr(graph, "run_crew", lambda *a, **k: fake_state())
    monkeypatch.setattr(
        api.report_pdf,
        "build_pdf",
        lambda state: "output/TEST_report.pdf",
    )

    response = client.post(
        "/analyse",
        json={
            "ticker": "TEST",
            "start_date": "2023-01-01",
            "end_date": "2024-01-01",
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["ticker"] == "TEST"
    assert body["report"].startswith("## Executive summary")
    assert "NaN" not in response.text
    assert body["fundamentals"]["metrics"]["net_margin"] is None
    assert body["fundamentals"]["series"]["revenue"][0]["period"] == "2023"


def test_analyse_turns_chart_paths_into_urls(monkeypatch, client):
    monkeypatch.setattr(graph, "run_crew", lambda *a, **k: fake_state())
    monkeypatch.setattr(
        api.report_pdf,
        "build_pdf",
        lambda state: "output/TEST_report.pdf",
    )

    body = client.post(
        "/analyse",
        json={
            "ticker": "TEST",
            "start_date": "2023-01-01",
            "end_date": "2024-01-01",
        },
    ).json()

    assert body["analysis"]["charts"]["price"] == "/charts/TEST_price.png"
    assert body["pdf_url"] == "/report/TEST/pdf"


def test_analyse_reports_a_crew_failure_as_a_500(monkeypatch, client):
    def boom(*args, **kwargs):
        raise RuntimeError("the provider is down")

    monkeypatch.setattr(graph, "run_crew", boom)
    response = client.post(
        "/analyse",
        json={
            "ticker": "TEST",
            "start_date": "2023-01-01",
            "end_date": "2024-01-01",
        },
    )

    assert response.status_code == 500
    assert "the provider is down" in response.json()["detail"]


def test_a_run_with_no_report_has_no_pdf_url(monkeypatch, client):
    monkeypatch.setattr(
        graph,
        "run_crew",
        lambda *a, **k: fake_state(report=""),
    )

    body = client.post(
        "/analyse",
        json={
            "ticker": "TEST",
            "start_date": "2023-01-01",
            "end_date": "2024-01-01",
        },
    ).json()

    assert body["pdf_url"] is None


def test_analyse_rejects_an_invalid_date_format(client):
    response = client.post(
        "/analyse",
        json={
            "ticker": "TEST",
            "start_date": "not-a-date",
            "end_date": "2024-01-01",
        },
    )

    assert response.status_code == 422


def test_analyse_rejects_start_date_after_end_date(client):
    response = client.post(
        "/analyse",
        json={
            "ticker": "TEST",
            "start_date": "2024-02-01",
            "end_date": "2024-01-01",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "start_date must be on or before end_date"


def events_from(response):
    return [
        json.loads(line)
        for line in response.text.splitlines()
        if line.strip()
    ]


def test_stream_sends_progress_then_one_result(monkeypatch, client):
    state = fake_state()

    def fake_stream(*args, **kwargs):
        yield {**state, "conversation_log": state["conversation_log"][:1]}
        yield state

    monkeypatch.setattr(graph, "stream_crew", fake_stream)
    monkeypatch.setattr(
        api.report_pdf,
        "build_pdf",
        lambda state: "output/TEST_report.pdf",
    )

    events = events_from(
        client.post(
            "/analyse/stream",
            json={
                "ticker": "TEST",
                "start_date": "2023-01-01",
                "end_date": "2024-01-01",
            },
        )
    )

    kinds = [event["event"] for event in events]
    assert kinds == ["progress", "progress", "result"]
    assert [event["agent"] for event in events[:2]] == [
        "orchestrator",
        "report_writer",
    ]
    assert events[-1]["result"]["ticker"] == "TEST"


def test_stream_sends_an_error_event_rather_than_dying_silently(monkeypatch, client):
    def boom(*args, **kwargs):
        raise RuntimeError("provider exploded")
        yield  # pragma: no cover

    monkeypatch.setattr(graph, "stream_crew", boom)
    events = events_from(
        client.post(
            "/analyse/stream",
            json={
                "ticker": "TEST",
                "start_date": "2023-01-01",
                "end_date": "2024-01-01",
            },
        )
    )

    assert events[-1]["event"] == "error"
    assert "provider exploded" in events[-1]["detail"]


def test_a_stream_that_yields_nothing_is_an_error_not_a_success(monkeypatch, client):
    def nothing(*args, **kwargs):
        return
        yield  # pragma: no cover

    monkeypatch.setattr(graph, "stream_crew", nothing)
    events = events_from(
        client.post(
            "/analyse/stream",
            json={
                "ticker": "TEST",
                "start_date": "2023-01-01",
                "end_date": "2024-01-01",
            },
        )
    )

    assert events[-1]["event"] == "error"


def test_a_missing_chart_is_a_404(client):
    assert client.get("/charts/does_not_exist.png").status_code == 404


def test_a_chart_name_with_a_path_in_it_is_refused(client):
    assert client.get("/charts/..%2F..%2Fsecret.txt").status_code in (400, 404)


def test_chart_route_refuses_non_png_files(client):
    assert client.get("/charts/run.log").status_code == 400


def test_a_missing_report_is_a_404(client):
    assert client.get("/report/NOSUCHTICKER/pdf").status_code == 404
