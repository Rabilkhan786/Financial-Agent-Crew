"""Tests for the specialists and the agent base — all mocked, no API calls.

We test the pure computation functions directly with fixture data, and test the
agents' wiring by injecting fake LLMs and monkeypatching the tool functions.
"""

from datetime import date

import pytest

from investpanel.agents.analyst import detect_contradictions
from investpanel.agents.base import BaseAgent
from investpanel.agents.financial import compute_findings
from investpanel.agents.news import NewsAgent
from investpanel.agents.risk import RiskAgent, compute_risk_findings
from investpanel.tools import alphavantage_client


class _FakeReply:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """Returns each queued reply in turn; the last repeats if over-called."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        return _FakeReply(reply)


# --- base agent -------------------------------------------------------------

def test_invoke_json_retries_bad_then_good():
    agent = BaseAgent(llm=_FakeLLM(["not json at all", '{"ok": true}']))
    assert agent.invoke_json("prompt") == {"ok": True}


def test_invoke_json_gives_up_after_retries():
    agent = BaseAgent(llm=_FakeLLM(["nope", "still nope"]))
    with pytest.raises(ValueError):
        agent.invoke_json("prompt", retries=2)


# --- financial (pure computation) -------------------------------------------

def _financial_fixture():
    income = [
        {"calendarYear": "2023", "revenue": 1200, "netIncome": 130,
         "operatingIncome": 200, "interestExpense": 20},
        {"calendarYear": "2022", "revenue": 1000, "netIncome": 100,
         "operatingIncome": 150, "interestExpense": 20},
    ]
    balance = [{"totalDebt": 500, "totalStockholdersEquity": 1000,
                "totalAssets": 2000, "totalCurrentLiabilities": 400}]
    cashflow = [{"operatingCashFlow": 150}]
    ratios = {"peRatioTTM": 18, "priceToBookRatioTTM": 3}
    return income, balance, cashflow, ratios


def test_compute_findings_produces_all_metrics_with_expected_values():
    findings = compute_findings(*_financial_fixture(), source="FMP test")
    by_metric = {f.metric: f for f in findings}

    # All ten checklist metrics computable from this fixture.
    assert set(by_metric) == {
        "revenue_growth", "profit_growth", "operating_cash_flow", "debt_to_equity",
        "interest_coverage", "roce", "roe", "pe_ratio", "pb_ratio", "valuation_vs_growth",
    }
    assert by_metric["revenue_growth"].value == 20.0
    assert by_metric["revenue_growth"].healthy is True
    assert by_metric["debt_to_equity"].value == 0.5
    assert by_metric["debt_to_equity"].healthy is True
    assert by_metric["interest_coverage"].value == 10.0
    assert by_metric["pe_ratio"].healthy is True
    # PEG-like = P/E 18 / profit growth 30% = 0.6
    assert by_metric["valuation_vs_growth"].value == pytest.approx(0.6, abs=0.01)
    # Every finding carries a source — the no-unsourced-facts rule.
    assert all(f.source for f in findings)


def test_compute_findings_skips_when_data_missing():
    # One year of income, no balance/cashflow/ratios -> nothing computable, no crash.
    income = [{"calendarYear": "2023", "revenue": 100, "netIncome": 10, "operatingIncome": 20}]
    assert compute_findings(income, [], [], {}, source="FMP test") == []


# --- risk (pure computation + parsing) --------------------------------------

def test_closing_prices_parses_and_orders_oldest_first():
    data = {
        "Time Series (Daily)": {
            "2023-01-03": {"4. close": "105"},
            "2023-01-01": {"4. close": "100"},
            "2023-01-02": {"4. close": "110"},
            "2023-01-04": {"4. close": "120"},
        }
    }
    assert alphavantage_client.closing_prices(data) == [100.0, 110.0, 105.0, 120.0]


def test_compute_risk_findings():
    findings = compute_risk_findings([100, 110, 105, 120], source="AV test")
    by_metric = {f.metric: f for f in findings}
    assert set(by_metric) == {"annualized_volatility", "max_drawdown"}
    # Worst drop: 110 -> 105 is (105-110)/110.
    assert by_metric["max_drawdown"].value == pytest.approx(5 / 110, abs=1e-4)
    assert all(f.computed_from for f in findings)


def test_risk_agent_uses_client(monkeypatch):
    fake_data = {
        "Time Series (Daily)": {
            "2023-01-01": {"4. close": "100"},
            "2023-01-02": {"4. close": "120"},
            "2023-01-03": {"4. close": "90"},
        },
        "source": "AV test",
    }
    monkeypatch.setattr(alphavantage_client, "get_daily_prices", lambda t: fake_data)
    findings = RiskAgent().analyze("ACME")
    assert {f.metric for f in findings} == {"annualized_volatility", "max_drawdown"}


# --- news (mocked search + fetch + llm) -------------------------------------

def test_analyst_catches_expensive_but_shrinking(monkeypatch):
    # Rich valuation (P/E flagged unhealthy) while profit is shrinking -> a real
    # valuation-vs-fundamentals contradiction the analyst must catch (the Tesla case).
    from investpanel.models.findings import FinancialFinding

    financial = [
        FinancialFinding(metric="pe_ratio", value=278.0, unit="ratio", period="TTM",
                         source="FMP", interpretation="expensive", healthy=False),
        FinancialFinding(metric="profit_growth", value=-46.8, unit="percent_yoy",
                         period="2025", source="FMP", interpretation="falling", healthy=False),
    ]
    contradictions = detect_contradictions(financial, [], [])
    assert len(contradictions) == 1
    c = contradictions[0]
    assert c.between == ("financial", "news")
    assert c.follow_up_target == "news"


def test_analyst_catches_earnings_quality_flag():
    # Profit growing but operating cash flow flagged unhealthy -> earnings-quality tension.
    from investpanel.models.findings import FinancialFinding

    financial = [
        FinancialFinding(metric="profit_growth", value=25.0, unit="percent_yoy", period="2025",
                         source="FMP", interpretation="up", healthy=True),
        FinancialFinding(metric="operating_cash_flow", value=-500.0, unit="currency", period="2025",
                         source="FMP", interpretation="weak vs profit", healthy=False),
    ]
    descriptions = [c.description for c in detect_contradictions(financial, [], [])]
    assert any("earnings-quality" in d for d in descriptions)


def test_analyst_catches_peer_lag():
    # Target growing far slower than its peers -> peer-relative contradiction.
    from investpanel.models.findings import FinancialFinding

    financial = [
        FinancialFinding(metric="revenue_growth", value=3.0, unit="percent_yoy", period="2025",
                         source="FMP", interpretation="slow", healthy=True),
    ]
    peer_comparison = {"revenue_growth": {"TGT": 3.0, "PEER1": 40.0, "PEER2": 35.0}}
    contradictions = detect_contradictions(
        financial, [], [], peer_comparison=peer_comparison, target_ticker="TGT"
    )
    assert any("behind its competitors" in c.description for c in contradictions)


def test_analyst_no_peer_lag_when_in_line():
    from investpanel.models.findings import FinancialFinding

    financial = [
        FinancialFinding(metric="revenue_growth", value=30.0, unit="percent_yoy", period="2025",
                         source="FMP", interpretation="fine", healthy=True),
    ]
    peer_comparison = {"revenue_growth": {"TGT": 30.0, "PEER1": 32.0, "PEER2": 28.0}}
    contradictions = detect_contradictions(
        financial, [], [], peer_comparison=peer_comparison, target_ticker="TGT"
    )
    assert not any("behind its competitors" in c.description for c in contradictions)


def test_analyst_no_contradiction_when_expensive_but_growing():
    # Expensive but GROWING is not a contradiction by this detector.
    from investpanel.models.findings import FinancialFinding

    financial = [
        FinancialFinding(metric="pe_ratio", value=35.0, unit="ratio", period="TTM",
                         source="FMP", interpretation="pricey", healthy=False),
        FinancialFinding(metric="profit_growth", value=19.0, unit="percent_yoy",
                         period="2025", source="FMP", interpretation="growing", healthy=True),
    ]
    assert detect_contradictions(financial, [], []) == []


def test_news_agent_only_keeps_fetchable_dated_articles(monkeypatch):
    from investpanel.tools import fetch, search

    results = [
        {"url": "https://a.com", "title": "A", "published_date": "2024-05-01"},
        {"url": "https://b.com", "title": "B"},  # fetch will fail -> skipped
        {"url": "https://c.com", "title": "C"},  # no date anywhere -> skipped
    ]
    monkeypatch.setattr(search, "search_news", lambda q, max_results=5: {"results": results})

    def fake_fetch(url):
        if url == "https://b.com":
            raise ValueError("cannot fetch")
        return "Some real article text about the company."

    monkeypatch.setattr(fetch, "fetch_article_text", fake_fetch)

    llm = _FakeLLM([
        (
            '{"summary": "A short summary.", "relevance": "high", '
            '"checklist_question": "risk", "published_date": null}'
        )
    ])
    findings = NewsAgent(llm=llm).analyze("Acme", max_articles=3)

    # Only a.com survives: b.com unfetchable, c.com has no usable date.
    assert len(findings) == 1
    f = findings[0]
    assert str(f.source_url) == "https://a.com/"  # HttpUrl normalizes the URL
    assert f.relevance == "high"
    assert f.checklist_question == "risk"
    assert f.published_date == date(2024, 5, 1)
