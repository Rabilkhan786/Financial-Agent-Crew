"""Connects all agents together using LangGraph.

START -> orchestrator -> (ticker invalid? -> END)
                       -> market_researcher -> fundamentals_analyst
      -> data_analyst -> report_writer -> orchestrator_review
      -> back to one of the two analysts, or END.

If the ticker is wrong, it stops early. If the review finds a problem, it
sends the work back to fix it.
"""

from langgraph.graph import END, START, StateGraph

from src import config, state
from src.agents import (data_analyst, fundamentals_analyst, market_researcher,
                        orchestrator, report_writer)

log = config.get_logger(__name__)


def build_graph():
    """Put the agents in order and connect them."""
    graph = StateGraph(state.CrewState)

    graph.add_node("orchestrator", orchestrator.run)
    graph.add_node("market_researcher", market_researcher.run)
    graph.add_node("fundamentals_analyst", fundamentals_analyst.run)
    graph.add_node("data_analyst", data_analyst.run)
    graph.add_node("report_writer", report_writer.run)
    graph.add_node("orchestrator_review", orchestrator.review)

    graph.add_edge(START, "orchestrator")

    # A ticker Yahoo cannot confirm goes straight to END: no news lookup, no
    # statement fetch, no price fetch for a company that does not exist.
    graph.add_conditional_edges(
        "orchestrator",
        orchestrator.route_after_intake,
        {"continue": "market_researcher", "invalid_ticker": END},
    )
    graph.add_edge("market_researcher", "fundamentals_analyst")
    graph.add_edge("fundamentals_analyst", "data_analyst")
    graph.add_edge("data_analyst", "report_writer")
    graph.add_edge("report_writer", "orchestrator_review")

    # The review sends the work back to one agent, or finishes. When it sends
    # work back, that agent runs again and the report is rewritten from there.
    graph.add_conditional_edges(
        "orchestrator_review",
        orchestrator.route,
        {
            "fundamentals_analyst": "fundamentals_analyst",
            "market_researcher": "market_researcher",
            "accept": END,
        },
    )

    return graph.compile()


def stream_crew(ticker, start_date, end_date):
    """Run the crew, handing back the whole state each time an agent finishes.

    LangGraph's stream does the work. stream_mode="values" yields a snapshot
    of the state after every step, so the app can show progress as it happens
    instead of sitting on a blank spinner for two minutes. Nothing here counts
    steps or tracks progress by hand.
    """
    crew = build_graph()
    starting_point = state.new_state(ticker, start_date, end_date)


    # recursion_limit is the backstop: even if the revise loop misbehaves,
    # LangGraph stops after this many steps.
    settings = {
        "run_name": f"crew-{ticker}",
        "tags": [ticker],
        "recursion_limit": config.RECURSION_LIMIT,
    }

    log.info("running the crew for %s", ticker)
    for snapshot in crew.stream(starting_point, config=settings, stream_mode="values"):
        yield snapshot


def run_crew(ticker, start_date, end_date):
    """Run the whole crew on one company and return the finished state.

    The same stream as above with only the last snapshot kept, so the app and
    the eval share one implementation rather than two that can drift.
    """
    finished = {}
    for snapshot in stream_crew(ticker, start_date, end_date):
        finished = snapshot

    log.info("finished %s: %d log entries, %d errors",
             ticker, len(finished.get("conversation_log", [])),
             len(finished.get("errors", [])))
    return finished
