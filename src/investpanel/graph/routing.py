"""The one branching decision in the graph: loop back, or write the report.

After the analyst runs, this function decides what happens next. If it found a
contradiction and we still have follow-up rounds left, we route to the single
specialist that contradiction targets. Otherwise we go write the report. The
round limit lives in config, so the loop is guaranteed to end — the same
discipline a real analyst has when working to a deadline.
"""

from investpanel import config
from investpanel.graph.state import PanelState
from investpanel.models.query_plan import QueryPlan


def route_after_manager(state: PanelState) -> list[str]:
    """Dispatch only the specialists this question actually needs.

    Returning a list makes LangGraph fan out to all of them in parallel. If the
    plan somehow asks for nobody, we go straight to the critic rather than
    stalling the graph — the report will say insufficient evidence, which is honest.
    """
    plan = state.get("query_plan") or QueryPlan()
    return plan.required_agents() or ["critic"]


def route_after_critic(state: PanelState) -> str:
    """Return the name of the next node: a specialist to re-ask, or "report".

    The returned string must match a node name in the workflow. We cap follow-ups
    at config.MAX_FOLLOWUP_ROUNDS so the critic -> specialist -> critic loop can
    never run forever.
    """
    contradictions = state.get("contradictions") or []
    rounds = state.get("rounds", 0)
    plan = state.get("query_plan") or QueryPlan()

    if contradictions and rounds < config.MAX_FOLLOWUP_ROUNDS:
        target = contradictions[0].follow_up_target  # "financial", "news", or "risk"
        # Never wake a specialist this question deliberately skipped — that would
        # quietly undo the routing decision and re-introduce the cost we avoided.
        if target in plan.required_agents():
            return target
    return "analyst"
