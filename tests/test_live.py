"""Checks that need the network and a working API key.

Skipped by default. Run them with:  pytest tests/ -q --live

These are the checks that catch what unit tests cannot: a provider changing its
response shape, a model name that no longer exists, a rate limit that turns a
report into a stub. Every one of those has actually happened here.
"""

import pathlib

import pytest

from src import charts, config, graph, report_pdf
from src.agents import (data_analyst, fundamentals_analyst, market_researcher,
                        orchestrator, report_writer)
from src.tools import kpi, market_data, news, ratios, social, sourcing

pytestmark = pytest.mark.live

TICKER = "BA"          # Boeing: fires three red flags, so the guards get exercised
START, END = "2023-01-01", "2026-08-15"


# --- Fetching ---------------------------------------------------------------

@pytest.fixture(scope="module")
def statements_for():
    from src.tools import statements
    return statements.fetch_statements(TICKER)


def test_statements_arrive_with_every_field(statements_for):
    assert statements_for["years"] >= 4
    assert statements_for["currency"] == "USD"
    assert len(statements_for["data"].columns) >= 11


def test_a_bad_ticker_degrades_rather_than_raising():
    from src.tools import statements
    assert statements.fetch_statements("NOTAREAL123")["error"]


@pytest.fixture(scope="module")
def market_for(statements_for):
    return market_data.fetch_market_data(TICKER, START, END,
                                         statements=statements_for["data"])


def test_prices_and_the_right_benchmark(market_for):
    assert len(market_for["prices"]) > 100
    assert market_for["benchmark_symbol"] == "^GSPC"
    assert "Boeing" in market_for["profile"]["name"]


def test_news_comes_back(market_for):
    assert news.fetch_news(TICKER, limit=3)["article_count"] >= 1


def test_social_gives_a_verdict_either_way():
    assert social.fetch_social_posts(TICKER)["social_sentiment"]
    assert social.fetch_social_posts("NOTAREAL123")["social_sentiment"] == "insufficient data"


# --- Maths on real data -----------------------------------------------------

def test_real_data_produces_real_ratios(statements_for, market_for):
    computed = ratios.compute_all(statements_for["data"],
                                  market_for["pe_current"], market_for["pe_history"],
                                  market_for["pb_current"], market_for["pb_history"])
    assert computed["latest"]["operating_margin"] is not None
    # Boeing is heavily borrowed and burns cash, so the rules must say something.
    assert computed["red_flags"], "the rules found nothing wrong with Boeing"


def test_charts_are_written_to_disk(statements_for, market_for):
    computed = ratios.compute_all(statements_for["data"])
    price = kpi.compute_all(market_for["prices"], market_for["benchmark_prices"])
    drawn = charts.build_all({"series": computed["series"], "currency": "USD"},
                             price["series"], "LIVETEST")
    assert len(drawn) == 5
    assert all(pathlib.Path(p).exists() for p in drawn.values())


# --- The model --------------------------------------------------------------

def test_the_model_answers():
    from src import llm
    assert llm.ask("Reply with exactly: OK")


def test_structured_output_fills_in_the_schema():
    from src import llm
    answer = llm.ask_structured(
        "A report ignores a red flag about debt. Is there a conflict?",
        orchestrator.ReviewDecision)
    assert answer is not None
    assert isinstance(answer.conflict, bool)


# --- The agents, one at a time ----------------------------------------------

@pytest.fixture(scope="module")
def crew():
    """State built up by running each agent in turn, as the graph would."""
    state = {"ticker": TICKER, "start_date": START, "end_date": END,
             "revision_count": 0, "max_revisions": 2, "conflicts": [],
             "conversation_log": [], "errors": []}
    state.update(orchestrator.run(state))
    state.update(market_researcher.run(state))
    state.update(fundamentals_analyst.run(state))
    state.update(data_analyst.run(state))
    state.update(report_writer.run(state))
    return state


def test_orchestrator_names_the_company(crew):
    assert "Boeing" in crew["company"]


def test_market_researcher_gathers_and_summarises(crew):
    assert crew["research"]["articles"]
    assert crew["research"]["summary"]


def test_fundamentals_analyst_reads_the_statements(crew):
    assert crew["fundamentals"]["available"]
    assert crew["fundamentals"]["interpretation"]
    assert crew["fundamentals"]["red_flags"]


def test_data_analyst_prices_it_and_draws_the_charts(crew):
    assert crew["analysis"]["available"]
    assert len(crew["analysis"]["charts"]) == 5


def test_report_writer_produces_every_section(crew):
    for heading in ("Executive summary", "Business quality", "Growth", "Profitability",
                    "Cash generation", "Balance sheet", "Valuation", "Market context",
                    "Recommendation", "Red flags"):
        assert f"## {heading}" in crew["report"], heading


def test_the_finished_report_has_no_unsourced_numbers(crew):
    assert sourcing.unsourced_numbers(crew) == []


def test_a_pdf_builds_from_the_finished_state(crew):
    assert pathlib.Path(report_pdf.build_pdf(crew)).exists()


# --- The whole graph --------------------------------------------------------

@pytest.fixture(scope="module")
def finished():
    return graph.run_crew(TICKER, START, END)


def test_the_graph_runs_start_to_finish(finished):
    assert len(finished["report"]) > 1500
    assert finished["errors"] == []


def test_every_agent_logged_a_step(finished):
    assert len(finished["conversation_log"]) >= 6


def test_revisions_stay_within_the_cap(finished):
    assert finished.get("revision_count", 0) <= finished["max_revisions"]


def test_streaming_yields_a_snapshot_per_step():
    seen = [snapshot for snapshot in graph.stream_crew("KO", START, END)]
    assert len(seen) >= 5
    assert "report" in seen[-1]
