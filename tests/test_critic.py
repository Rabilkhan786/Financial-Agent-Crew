"""Tests for CHANGE 3: the Critic step between the specialists and the Analyst.

What matters here is that the Critic actually separates real contradictions from
softer tensions, that its findings reach the Analyst, and that the Analyst is told
to address them rather than quietly reconciling them. All mocked.
"""

from investpanel.agents.critic import CriticAgent
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding


def _ff(metric, value, healthy, unit="ratio"):
    return FinancialFinding(metric=metric, value=value, unit=unit, period="2025",
                             source="FMP test", interpretation="x", healthy=healthy)


def _rf(metric, value):
    return RiskFinding(metric=metric, value=value,
                        computed_from="100-day close series, AV test", interpretation="x")


def _nf(headline, tag="risk"):
    return NewsFinding(headline=headline, summary="s", source_url="https://e.com",
                        published_date="2026-08-01", relevance="high", checklist_question=tag)


def test_critic_finds_nothing_when_everything_agrees():
    contradictions, tensions = CriticAgent().review(
        [_ff("revenue_growth", 10.0, True), _ff("profit_growth", 12.0, True)],
        [], [_rf("annualized_volatility", 0.15)],
    )
    assert contradictions == []
    assert tensions == []


def test_critic_reports_a_real_contradiction():
    # Rich valuation while profit shrinks — a genuine numbers-vs-price conflict.
    contradictions, _ = CriticAgent().review(
        [_ff("pe_ratio", 278.0, False), _ff("profit_growth", -46.8, False, "percent_yoy")],
        [], [],
    )
    assert len(contradictions) == 1
    assert contradictions[0].follow_up_target == "news"


def test_critic_separates_a_tension_from_a_contradiction():
    # Revenue up while profit falls is worth flagging, but is NOT a contradiction.
    financial = [
        _ff("revenue_growth", 19.2, True, "percent_yoy"),
        _ff("profit_growth", -3.4, False, "percent_yoy"),
    ]
    contradictions, tensions = CriticAgent().review(financial, [], [])
    assert contradictions == []          # must not overstate
    assert len(tensions) == 1            # but must not stay silent either


def test_critic_catches_cash_versus_profit_conflict():
    # The example from the brief: healthy-looking profit next to weak cash flow.
    financial = [
        _ff("profit_growth", 25.0, True, "percent_yoy"),
        _ff("operating_cash_flow", -500.0, False, "currency"),
    ]
    contradictions, _ = CriticAgent().review(financial, [], [])
    assert any("earnings-quality" in c.description for c in contradictions)


def test_critic_uses_peer_data_when_given_it():
    financial = [_ff("revenue_growth", 3.0, True, "percent_yoy")]
    peers = {"revenue_growth": {"TGT": 3.0, "P1": 40.0, "P2": 35.0}}
    contradictions, _ = CriticAgent().review(financial, [], [], peer_comparison=peers,
                                              target_ticker="TGT")
    assert any("behind its competitors" in c.description for c in contradictions)


def test_critic_findings_reach_the_report_through_the_analyst():
    from investpanel.agents.analyst import AnalystAgent
    from investpanel.models.contradiction import Tension

    tension = Tension(between=("financial", "financial"), description="d", reason="r")
    report = AnalystAgent().write_report(
        company="Acme", company_description="x",
        financial=[], news=[], risk=[], contradictions=[],
        contradictions_resolved=0, peer_comparison={}, tensions=[tension],
    )
    # The Analyst must carry the Critic's tension through, not drop it.
    assert report.potential_tensions == [tension]


def test_analyst_prompt_tells_the_model_to_address_the_critic():
    from investpanel.agents.analyst import AnalystAgent
    from investpanel.models.contradiction import Contradiction

    seen = {}

    class CapturingLLM:
        def invoke(self, prompt):
            seen["prompt"] = prompt

            class R:
                content = "A takeaway with no numbers in it."
            return R()

    contradiction = Contradiction(between=("financial", "news"), description="d",
                                   follow_up_target="news", follow_up_question="q?")
    AnalystAgent(llm=CapturingLLM())._summary("Acme", [], [], [], [contradiction], [])
    assert "MUST acknowledge them" in seen["prompt"]


def test_no_critic_note_when_there_is_nothing_to_address():
    from investpanel.agents.analyst import AnalystAgent

    seen = {}

    class CapturingLLM:
        def invoke(self, prompt):
            seen["prompt"] = prompt

            class R:
                content = "All quiet."
            return R()

    AnalystAgent(llm=CapturingLLM())._summary("Acme", [], [], [], [], [])
    assert "MUST acknowledge them" not in seen["prompt"]
