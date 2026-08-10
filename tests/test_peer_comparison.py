"""Tests for CHANGE 4: competitor comparison, end to end.

The comparison already existed; what was missing was verification of the competitor
tickers (so peers stopped silently dropping out) and a side-by-side table that says
where the target actually stands. Both are pinned here. All mocked.
"""

from investpanel.agents.manager import ManagerAgent
from investpanel.models.report import Report
from investpanel.tools import fmp_client, search
from investpanel.utils.report_analysis import build_peer_table


class _FakeReply:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self, reply):
        self._reply = reply

    def invoke(self, prompt):
        return _FakeReply(self._reply)


# --- competitor discovery is verified, not trusted ---------------------------------

def test_competitors_are_verified_against_real_tickers(monkeypatch):
    # The model proposes three peers; only two are real symbols.
    monkeypatch.setattr(search, "search_news",
                        lambda q, max_results=5: {"results": [{"title": "peers", "url": "https://e.com"}]})
    monkeypatch.setattr(fmp_client, "search_symbol", lambda q, limit=10: [])
    monkeypatch.setattr(fmp_client, "search_name", lambda q, limit=10: [])

    real = {"ADDYY", "UAA"}
    monkeypatch.setattr(
        fmp_client, "get_company_profile",
        lambda t: {"companyName": t} if t.upper() in real else (_ for _ in ()).throw(ValueError("no profile")),
    )

    llm = _FakeLLM(
        '{"competitors": [{"name": "Adidas", "ticker": "ADDYY"},'
        ' {"name": "Under Armour", "ticker": "UAA"},'
        ' {"name": "Made Up Co", "ticker": "NOTREAL"}]}'
    )
    competitors = ManagerAgent(llm=llm)._find_competitors("Nike")

    assert competitors == ["ADDYY", "UAA"]   # the unverifiable one is dropped
    assert "NOTREAL" not in competitors


def test_competitor_list_is_capped(monkeypatch):
    from investpanel import config

    monkeypatch.setattr(search, "search_news",
                        lambda q, max_results=5: {"results": [{"title": "peers", "url": "https://e.com"}]})
    monkeypatch.setattr(fmp_client, "search_symbol", lambda q, limit=10: [])
    monkeypatch.setattr(fmp_client, "search_name", lambda q, limit=10: [])
    monkeypatch.setattr(fmp_client, "get_company_profile", lambda t: {"companyName": t})

    many = ", ".join(f'{{"name": "C{i}", "ticker": "T{i}"}}' for i in range(8))
    competitors = ManagerAgent(llm=_FakeLLM('{"competitors": [' + many + "]}"))._find_competitors("Acme")
    assert len(competitors) == config.MAX_COMPETITORS


def test_duplicate_competitors_are_not_repeated(monkeypatch):
    monkeypatch.setattr(search, "search_news",
                        lambda q, max_results=5: {"results": [{"title": "peers", "url": "https://e.com"}]})
    monkeypatch.setattr(fmp_client, "search_symbol", lambda q, limit=10: [])
    monkeypatch.setattr(fmp_client, "search_name", lambda q, limit=10: [])
    monkeypatch.setattr(fmp_client, "get_company_profile", lambda t: {"companyName": t})

    llm = _FakeLLM('{"competitors": [{"name": "A", "ticker": "AAA"}, {"name": "A again", "ticker": "AAA"}]}')
    assert ManagerAgent(llm=llm)._find_competitors("Acme") == ["AAA"]


def test_no_search_results_means_no_competitors(monkeypatch):
    monkeypatch.setattr(search, "search_news", lambda q, max_results=5: {"results": []})
    assert ManagerAgent(llm=_FakeLLM("{}"))._find_competitors("Acme") == []


# --- the side-by-side table ----------------------------------------------------------

def test_peer_table_says_where_the_target_stands():
    table = build_peer_table(
        {"revenue_growth": {"NKE": 5.0, "ADDYY": 15.0, "UAA": 25.0}}, target_ticker="NKE"
    )
    row = table[0]
    assert row["Metric"] == "Revenue Growth"
    assert row["NKE"] == "+5.00% YoY"
    # Peer average is 20%; the target is well below it, which is unfavourable here.
    assert "below peer avg" in row["vs peers"]
    assert "unfavourable" in row["vs peers"]


def test_peer_table_knows_a_lower_number_can_be_better():
    # Being BELOW the peer average on debt is a good thing, not a shortfall.
    table = build_peer_table(
        {"debt_to_equity": {"NKE": 0.5, "ADDYY": 1.5, "UAA": 1.5}}, target_ticker="NKE"
    )
    assert "favourable" in table[0]["vs peers"]
    assert "unfavourable" not in table[0]["vs peers"]


def test_peer_table_handles_having_no_peers():
    table = build_peer_table({"revenue_growth": {"NKE": 5.0}}, target_ticker="NKE")
    assert table[0]["vs peers"] == "no peer data"


def test_peer_table_rows_follow_the_checklist_order():
    table = build_peer_table(
        {"pe_ratio": {"A": 10.0}, "revenue_growth": {"A": 5.0}, "net_margin": {"A": 0.2}},
        target_ticker="A",
    )
    assert [r["Metric"] for r in table] == ["Revenue Growth", "Net Margin", "P/E Ratio"]


def test_peer_table_is_empty_without_data():
    assert build_peer_table({}, target_ticker="NKE") == []


def test_report_carries_the_peer_comparison_through():
    report = Report(company="Nike", ticker="NKE", company_description="x", summary="s",
                     peer_comparison={"revenue_growth": {"NKE": 5.0, "ADDYY": 15.0}})
    rows = build_peer_table(report.peer_comparison, report.ticker)
    assert rows and "ADDYY" in rows[0]
