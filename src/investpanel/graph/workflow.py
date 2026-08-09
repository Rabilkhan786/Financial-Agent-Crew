"""Wire the agents into the LangGraph panel.

Flow: manager sets scope -> Financial, News, and Risk run in parallel -> the
Analyst cross-checks -> if it found a contradiction (and rounds remain) the graph
loops back to ONE specialist and then to the Analyst again -> finally the report.

The five agents are held in a small ``Panel`` and passed in, so the whole graph
can be built and tested with fake agents (no API keys). ``build_panel`` makes the
real ones; tests make their own.
"""

from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph

from investpanel import config
from investpanel.agents.analyst import AnalystAgent
from investpanel.agents.financial import FinancialAgent
from investpanel.agents.manager import ManagerAgent
from investpanel.agents.news import NewsAgent
from investpanel.agents.risk import RiskAgent
from investpanel.graph.routing import route_after_analyst
from investpanel.graph.state import PanelState


@dataclass
class Panel:
    """The five agents that make up the panel."""

    manager: object
    financial: object
    news: object
    risk: object
    analyst: object


def build_panel() -> Panel:
    """Construct the real agents. Each needs its API key only when actually run."""
    return Panel(
        manager=ManagerAgent(),
        financial=FinancialAgent(),
        news=NewsAgent(),
        risk=RiskAgent(),
        analyst=AnalystAgent(),
    )


def _is_followup_for(state: PanelState, specialist: str) -> bool:
    """True when the graph looped back specifically to this specialist."""
    follow_up = state.get("follow_up")
    return bool(follow_up and follow_up.follow_up_target == specialist)


def build_workflow(panel: Panel):
    """Build and compile the LangGraph workflow for the given panel."""

    def manager_node(state: PanelState) -> dict:
        scope = panel.manager.plan(state["question"])
        description = panel.manager.company_description(scope.ticker)
        return {"scope": scope, "company_description": description, "rounds": 0}

    def financial_node(state: PanelState) -> dict:
        scope = state["scope"]
        followup = _is_followup_for(state, "financial")
        try:
            update: dict = {"financial_findings": panel.financial.analyze(scope.ticker)}
            if not followup:
                # Build the peer table once, on the first pass, from target + competitors.
                tickers = [t for t in [scope.ticker, *scope.competitors] if t]
                update["peer_comparison"] = panel.financial.peer_metric_table(tickers)
        except Exception as error:  # noqa: BLE001 - graceful degradation: one specialist failing must not sink the run
            update = {"financial_findings": [], "errors": [f"financial: {error}"]}
        if followup:
            update["rounds"] = state.get("rounds", 0) + 1
        return update

    def news_node(state: PanelState) -> dict:
        scope = state["scope"]
        followup = _is_followup_for(state, "news")
        focus = state["follow_up"].follow_up_question if followup else None
        try:
            update: dict = {"news_findings": panel.news.analyze(scope.company, focus=focus)}
        except Exception as error:  # noqa: BLE001 - graceful degradation
            update = {"news_findings": [], "errors": [f"news: {error}"]}
        if followup:
            update["rounds"] = state.get("rounds", 0) + 1
        return update

    def risk_node(state: PanelState) -> dict:
        scope = state["scope"]
        followup = _is_followup_for(state, "risk")
        try:
            update: dict = {"risk_findings": panel.risk.analyze(scope.ticker)}
        except Exception as error:  # noqa: BLE001 - graceful degradation
            update = {"risk_findings": [], "errors": [f"risk: {error}"]}
        if followup:
            update["rounds"] = state.get("rounds", 0) + 1
        return update

    def analyst_node(state: PanelState) -> dict:
        contradictions = panel.analyst.cross_check(
            state.get("financial_findings", []),
            state.get("news_findings", []),
            state.get("risk_findings", []),
        )
        return {
            "contradictions": contradictions,
            "follow_up": contradictions[0] if contradictions else None,
            "all_contradictions": contradictions,  # add-reducer accumulates these
        }

    def report_node(state: PanelState) -> dict:
        scope = state["scope"]
        report = panel.analyst.write_report(
            company=scope.company,
            company_description=state.get("company_description", ""),
            financial=state.get("financial_findings", []),
            news=state.get("news_findings", []),
            risk=state.get("risk_findings", []),
            contradictions=_dedup(state.get("all_contradictions", [])),
            contradictions_resolved=state.get("rounds", 0),
            peer_comparison=state.get("peer_comparison", {}),
        )
        return {"report": report}

    builder = StateGraph(PanelState)
    builder.add_node("manager", manager_node)
    builder.add_node("financial", financial_node)
    builder.add_node("news", news_node)
    builder.add_node("risk", risk_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("report", report_node)

    builder.add_edge(START, "manager")
    # Manager fans out to the three specialists, which run in parallel.
    builder.add_edge("manager", "financial")
    builder.add_edge("manager", "news")
    builder.add_edge("manager", "risk")
    # The three fan back in to the analyst (it waits for all three).
    builder.add_edge("financial", "analyst")
    builder.add_edge("news", "analyst")
    builder.add_edge("risk", "analyst")
    # After the analyst: loop to one specialist, or finish with the report.
    builder.add_conditional_edges(
        "analyst",
        route_after_analyst,
        {"financial": "financial", "news": "news", "risk": "risk", "report": "report"},
    )
    builder.add_edge("report", END)

    return builder.compile()


def _dedup(contradictions: list) -> list:
    """Drop repeated contradictions (same description) accumulated across passes."""
    seen = set()
    unique = []
    for c in contradictions:
        if c.description not in seen:
            seen.add(c.description)
            unique.append(c)
    return unique


def run_panel(question: str):
    """Convenience: run the real panel end to end and return the Report.

    Needs all API keys. The recursion limit is set generously above the small
    number of loop steps our bounded follow-up can produce.
    """
    workflow = build_workflow(build_panel())
    # Each round adds ~2 steps (specialist + analyst); give clear headroom.
    limit = 10 + config.MAX_FOLLOWUP_ROUNDS * 3
    final_state = workflow.invoke({"question": question}, {"recursion_limit": limit})
    return final_state["report"]
