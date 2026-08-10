"""Wire the agents into the LangGraph panel.

Flow: the Query Analyzer classifies the question -> the Manager sets scope and
dispatches ONLY the specialists that question needs -> they run in parallel -> the
Critic cross-examines their findings -> if it found a contradiction (and rounds
remain) the graph loops back to ONE specialist and through the Critic again ->
finally the Analyst synthesizes the report, addressing what the Critic raised.

The agents are held in a small ``Panel`` and passed in, so the whole graph can be
built and tested with fake agents (no API keys). ``build_panel`` makes the real
ones; tests make their own.
"""

from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph

from investpanel import config
from investpanel.agents.analyst import AnalystAgent
from investpanel.agents.critic import CriticAgent
from investpanel.agents.financial import FinancialAgent
from investpanel.agents.manager import ManagerAgent
from investpanel.agents.news import NewsAgent
from investpanel.agents.query_analyzer import QueryAnalyzerAgent
from investpanel.agents.risk import RiskAgent
from investpanel.graph.routing import route_after_critic, route_after_manager
from investpanel.graph.state import PanelState
from investpanel.models.query_plan import QueryPlan
from investpanel.models.scope import ResearchScope
from investpanel.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Panel:
    """The agents that make up the panel."""

    manager: object
    financial: object
    news: object
    risk: object
    analyst: object
    # Runs before the manager to decide which specialists this question needs.
    query_analyzer: object = None
    # Cross-examines the specialists between their work and the analyst's synthesis.
    critic: object = None


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
        query_analyzer=QueryAnalyzerAgent(),
        # The critic gets the stronger model too when one is configured — judging
        # whether findings genuinely conflict is the reasoning-heavy step.
        critic=CriticAgent(llm=get_llm(model=config.ANALYST_MODEL)) if config.ANALYST_MODEL
        else CriticAgent(),
    )


def _is_followup_for(state: PanelState, specialist: str) -> bool:
    """True when the graph looped back specifically to this specialist."""
    follow_up = state.get("follow_up")
    return bool(follow_up and follow_up.follow_up_target == specialist)


def build_workflow(panel: Panel):
    """Build and compile the LangGraph workflow for the given panel."""

    def manager_node(state: PanelState) -> dict:
        # The manager is the one node whose failure used to kill the whole run: a
        # transient rate limit here meant the user saw an error instead of a report.
        # Degrade to a minimal scope built from the question itself so the
        # specialists can still try, and record why the scope is thin.
        question = state["question"]
        try:
            scope = panel.manager.plan(question)
        except Exception as error:  # noqa: BLE001 - degrade rather than lose the run
            logger.warning("Manager could not plan the question: %s", error)
            return {
                "scope": ResearchScope(company=question, clarified_question=question),
                "company_description": "",
                "rounds": 0,
                "errors": [f"manager: {error}"],
            }
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

        # Build the peer table separately (first pass only, and only when this
        # question actually wants a peer comparison — it's several extra API calls).
        # A failure here must NOT discard the target's own findings, so it's in its
        # own try.
        plan = state.get("query_plan") or QueryPlan()
        if not followup and plan.needs_peers:
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

    def critic_node(state: PanelState) -> dict:
        """Challenge the specialists BEFORE the analyst gets to tell a tidy story."""
        scope = state.get("scope")
        if panel.critic is None:
            # No critic supplied (older callers / focused tests): skip the challenge
            # rather than crash, and record that nothing was cross-examined.
            return {"contradictions": [], "tensions": [], "observations": [], "follow_up": None}
        contradictions, tensions, observations = panel.critic.review(
            state.get("financial_findings", []),
            state.get("news_findings", []),
            state.get("risk_findings", []),
            peer_comparison=state.get("peer_comparison"),
            target_ticker=scope.ticker if scope else None,
        )
        return {
            "contradictions": contradictions,
            "tensions": tensions,
            "observations": observations,
            "follow_up": contradictions[0] if contradictions else None,
            "all_contradictions": contradictions,  # add-reducer accumulates these
        }

    def analyst_node(state: PanelState) -> dict:
        scope = state["scope"]
        plan = state.get("query_plan") or QueryPlan()
        report = panel.analyst.write_report(
            query_intent=plan.intent,
            routing_reason=plan.reasoning,
            skipped_agents=plan.skipped_agents(),
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
            # The Critic's findings are handed to the Analyst as input it must
            # address, not something it can quietly reconcile away.
            tensions=state.get("tensions", []),
            additional_findings=state.get("observations", []),
            peer_comparison=state.get("peer_comparison", {}),
            followup_targets_executed=state.get("resolved_targets", []),
        )
        return {"report": report}

    def query_analyzer_node(state: PanelState) -> dict:
        # No analyzer supplied (older callers, and tests that don't care about
        # routing) means the panel behaves exactly as before: run everything.
        if panel.query_analyzer is None:
            return {"query_plan": QueryPlan()}
        return {"query_plan": panel.query_analyzer.plan_query(state["question"])}

    builder = StateGraph(PanelState)
    builder.add_node("query_analyzer", query_analyzer_node)
    builder.add_node("manager", manager_node)
    builder.add_node("financial", financial_node)
    builder.add_node("news", news_node)
    builder.add_node("risk", risk_node)
    builder.add_node("critic", critic_node)
    builder.add_node("analyst", analyst_node)

    # Classify the question first, so the Manager knows who to wake up.
    builder.add_edge(START, "query_analyzer")
    builder.add_edge("query_analyzer", "manager")
    # The Manager fans out to ONLY the specialists this question needs. Returning a
    # list from the router makes LangGraph run them in parallel, as before — the
    # difference is that a risk-only question no longer pays for news and FMP calls.
    builder.add_conditional_edges(
        "manager",
        route_after_manager,
        {"financial": "financial", "news": "news", "risk": "risk", "critic": "critic"},
    )
    # Whoever ran fans back in to the CRITIC, not straight to the analyst — every
    # set of findings gets challenged before anyone synthesizes them.
    builder.add_edge("financial", "critic")
    builder.add_edge("news", "critic")
    builder.add_edge("risk", "critic")
    # The critic decides: send one specialist back for another look, or hand its
    # findings to the analyst to write up.
    builder.add_conditional_edges(
        "critic",
        route_after_critic,
        {"financial": "financial", "news": "news", "risk": "risk", "analyst": "analyst"},
    )
    builder.add_edge("analyst", END)

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
