"""LangGraph workflow for the financial analysis crew."""

from langgraph.graph import END, START, StateGraph

from src.agents import (
    data_analyst,
    fundamentals_analyst,
    market_researcher,
    orchestrator,
    report_writer,
)
from src.components import config
from src.components.logging import get_logger
from src.core import state

log = get_logger(__name__)


def build_graph():
    """Create and compile the agent workflow."""
    graph = StateGraph(state.CrewState)

    graph.add_node("orchestrator", orchestrator.run)
    graph.add_node("market_researcher", market_researcher.run)
    graph.add_node("fundamentals_analyst", fundamentals_analyst.run)
    graph.add_node("data_analyst", data_analyst.run)
    graph.add_node("report_writer", report_writer.run)
    graph.add_node("orchestrator_review", orchestrator.review)

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        orchestrator.route_after_intake,
        {"continue": "market_researcher", "stop": END},
    )

    graph.add_edge("market_researcher", "fundamentals_analyst")
    graph.add_edge("fundamentals_analyst", "data_analyst")
    graph.add_edge("data_analyst", "report_writer")
    graph.add_edge("report_writer", "orchestrator_review")

    graph.add_conditional_edges(
        "orchestrator_review",
        orchestrator.route_after_review,
        {
            "market_researcher": "market_researcher",
            "fundamentals_analyst": "fundamentals_analyst",
            "accept": END,
        },
    )

    return graph.compile()


def stream_crew(ticker, start_date, end_date):
    """Run the workflow and yield the shared state after each node."""
    workflow = build_graph()
    initial_state = state.new_state(ticker, start_date, end_date)

    log.info("Starting analysis for %s", ticker)
    yield from workflow.stream(
        initial_state,
        config={"recursion_limit": config.RECURSION_LIMIT},
        stream_mode="values",
    )
