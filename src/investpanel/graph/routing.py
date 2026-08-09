"""The one branching decision in the graph: loop back, or write the report.

After the analyst runs, this function decides what happens next. If it found a
contradiction and we still have follow-up rounds left, we route to the single
specialist that contradiction targets. Otherwise we go write the report. The
round limit lives in config, so the loop is guaranteed to end — the same
discipline a real analyst has when working to a deadline.
"""

from investpanel import config
from investpanel.graph.state import PanelState


def route_after_analyst(state: PanelState) -> str:
    """Return the name of the next node: a specialist to re-ask, or "report".

    The returned string must match a node name in the workflow. We cap follow-ups
    at config.MAX_FOLLOWUP_ROUNDS so the analyst -> specialist -> analyst loop can
    never run forever.
    """
    contradictions = state.get("contradictions") or []
    rounds = state.get("rounds", 0)

    if contradictions and rounds < config.MAX_FOLLOWUP_ROUNDS:
        # Follow up with the ONE specialist this contradiction points at.
        return contradictions[0].follow_up_target  # "financial", "news", or "risk"
    return "report"
