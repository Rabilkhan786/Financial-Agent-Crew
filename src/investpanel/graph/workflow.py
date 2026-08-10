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
from investpanel.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Panel:
    """The five agents that make up the panel."""

    manager: object
    financial: object
    news: object
    risk: object
    analyst: object


def build_panel() -> Panel:
    """Construct the real agents. Each needs its API key only when actually run.

    If config.ANALYST_MODEL is set, the analyst gets that (stronger) model while the
    specialists use the default — its cross-check is the reasoning-heavy step.
    """
    from investpanel.llm.factory import get_llm

    analyst = AnalystAgent()
    if config.ANALYST_MODEL:
        analyst = AnalystAgent(llm=get_llm(model=config.ANALYST_MODEL))

    return Panel(
        manager=ManagerAgent(),
        financial=FinancialAgent(),
        news=NewsAgent(),
        risk=RiskAgent(),
        analyst=analyst,
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
        update: dict = {}

        # Analyse the target on its own. If this fails, we degrade to no financials.
        try:
            update["financial_findings"] = panel.financial.analyze(scope.ticker)
        except Exception as error:  # noqa: BLE001 - graceful degradation
            update["financial_findings"] = []
            update["errors"] = [f"financial: {error}"]

        # Build the peer table separately (first pass only). A failure here must NOT
        # discard the target's own findings, so it's in its own try.
        if not followup:
            try:
                tickers = [t for t in [scope.ticker, *scope.competitors] if t]
                update["peer_comparison"] = panel.financial.peer_metric_table(tickers)
            except Exception as error:  # noqa: BLE001 - peer table is a nice-to-have
                update["errors"] = update.get("errors", []) + [f"peer_comparison: {error}"]

        if followup:
            update["rounds"] = state.get("rounds", 0) + 1
            update["resolved_targets"] = ["financial"]
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
            update["resolved_targets"] = ["news"]
        return update

    def risk_node(state: PanelState) -> dict:
        scope = state["scope"]
        followup = _is_followup_for(state, "risk")
        try:
            update: dict = {"risk_findings": panel.risk.analyze(scope.ticker)}
            # Keep the prices for the report's chart. Cached, so no extra API call —
            # and a chart is a nice-to-have, so a failure here is silently skipped.
            try:
                update["price_history"] = panel.risk.price_series(scope.ticker)
            except Exception as chart_error:  # noqa: BLE001 - chart data is optional
                logger.warning("No price series for the chart: %s", chart_error)
        except Exception as error:  # noqa: BLE001 - graceful degradation
            update = {"risk_findings": [], "errors": [f"risk: {error}"]}
        if followup:
            update["rounds"] = state.get("rounds", 0) + 1
            update["resolved_targets"] = ["risk"]
        return update

    def analyst_node(state: PanelState) -> dict:
        scope = state.get("scope")
        contradictions = panel.analyst.cross_check(
            state.get("financial_findings", []),
            state.get("news_findings", []),
            state.get("risk_findings", []),
            peer_comparison=state.get("peer_comparison"),
            target_ticker=scope.ticker if scope else None,
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
            ticker=scope.ticker,
            question=state.get("question"),
            interpreted_question=scope.clarified_question,
            company_description=state.get("company_description", ""),
            financial=state.get("financial_findings", []),
            news=state.get("news_findings", []),
            risk=state.get("risk_findings", []),
            price_history=state.get("price_history", []),
            contradictions=_dedup(state.get("all_contradictions", [])),
            contradictions_resolved=state.get("rounds", 0),
            peer_comparison=state.get("peer_comparison", {}),
            followup_targets_executed=state.get("resolved_targets", []),
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
    number of loop steps our bounded follow-up can produce. We also write one
    consolidated "panel_run" trace so the observability tab has per-run numbers
    (latency, completeness, whether the loop fired) to aggregate later.
    """
    import time

    from investpanel.utils.tracing import init_langsmith, save_trace

    # Send the whole multi-agent run to LangSmith too, if a key is configured.
    init_langsmith()

    workflow = build_workflow(build_panel())
    # Each round adds ~2 steps (specialist + analyst); give clear headroom.
    limit = 10 + config.MAX_FOLLOWUP_ROUNDS * 3

    start = time.perf_counter()
    final_state = workflow.invoke({"question": question}, {"recursion_limit": limit})
    latency = round(time.perf_counter() - start, 3)

    report = final_state["report"]
    answered = sum(
        1 for v in report.checklist_answers.values()
        if v and "insufficient evidence" not in v.lower()
    )
    total = len(report.checklist_answers) or 1
    save_trace("panel_run", {
        "company": report.company,
        "question": question,
        "latency_seconds": latency,
        "contradictions_found": len(report.contradictions_found),
        "contradictions_resolved": report.contradictions_resolved,
        "loop_fired": report.contradictions_resolved > 0,
        "checklist_completeness": round(answered / total, 3),
        "num_financial": len(report.financial_findings),
        "num_news": len(report.news_findings),
        "num_risk": len(report.risk_findings),
        "errors": final_state.get("errors", []),
    })
    return report
