"""FastAPI tests with the LangGraph workflow stubbed out."""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
from src.core import graph


@pytest.fixture
def client():
    return TestClient(api.app)


def fake_state(report="## Executive summary\nAll good."):
    return {
        "ticker": "TEST",
        "company": "Test Company",
        "report": report,
        "errors": [],
        "conversation_log": [
            {"agent": "orchestrator", "message": "started"},
            {"agent": "report_writer", "message": "finished"},
        ],
        "fundamentals": {
            "available": True,
            "metrics": {
                "operating_margin": 0.20,
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


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert "model" in response.json()


def test_analyse_returns_json_safe_result(monkeypatch, client):
    monkeypatch.setattr(graph, "run_crew", lambda *args: fake_state())
    monkeypatch.setattr(api.report_pdf, "build_pdf", lambda state: "report.pdf")

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
    assert body["fundamentals"]["metrics"]["net_margin"] is None
    assert body["analysis"]["charts"]["price"] == "/charts/TEST_price.png"
    assert body["pdf_url"] == "/report/TEST/pdf"


def test_invalid_date_range_is_rejected(client):
    response = client.post(
        "/analyse",
        json={
            "ticker": "TEST",
            "start_date": "2024-02-01",
            "end_date": "2024-01-01",
        },
    )
    assert response.status_code == 422


def test_stream_returns_progress_and_result(monkeypatch, client):
    state = fake_state()

    def fake_stream(*args):
        yield {**state, "conversation_log": state["conversation_log"][:1]}
        yield state

    monkeypatch.setattr(graph, "stream_crew", fake_stream)
    monkeypatch.setattr(api.report_pdf, "build_pdf", lambda state: "report.pdf")

    response = client.post(
        "/analyse/stream",
        json={
            "ticker": "TEST",
            "start_date": "2023-01-01",
            "end_date": "2024-01-01",
        },
    )

    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert [event["event"] for event in events] == [
        "progress",
        "progress",
        "result",
    ]


def test_missing_chart_is_404(client):
    assert client.get("/charts/missing.png").status_code == 404
