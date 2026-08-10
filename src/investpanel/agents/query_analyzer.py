"""Query Analyzer — decides what the question actually needs before anyone works.

Runs first, ahead of the Manager. It reads the question and classifies it into one
intent; the intent then determines which specialists the graph dispatches. A
question like "what is Nike's P/E?" no longer pays for a news search and a price
download it never uses.

Two deliberate choices:
  - the LLM only picks a LABEL, never the agent list. Routing is control flow, so
    the label -> agents mapping is a Python table in models/query_plan.py.
  - any failure (no key, bad JSON, rate limit) falls back to full due diligence.
    Running too much is a cost problem; running too little is a correctness
    problem, and correctness wins.
"""

from investpanel.agents.base import BaseAgent
from investpanel.models.query_plan import DEFAULT_INTENT, QueryPlan
from investpanel.utils.logging import get_logger

logger = get_logger(__name__)

CLASSIFY_PROMPT = """Classify what this investment question is asking for.
Pick exactly ONE intent from this list:

  "quick_fact"             - wants one specific number or figure (e.g. "what is Nike's P/E?")
  "financial_health"       - fundamentals only (profits, debt, margins, growth)
  "risk_only"              - about volatility, downside, or how risky the stock is
  "news_only"              - about recent events, announcements, or what's happening
  "competitor_comparison"  - compares the company against rivals or its industry
  "full_due_diligence"     - a broad "is this a good investment?" question, or anything
                             that needs fundamentals AND news AND risk together

If the question is broad, vague, or you are unsure, choose "full_due_diligence".

Return ONLY JSON:
  {{"intent": "<one of the labels above>",
    "reasoning": "one short sentence explaining the choice"}}

QUESTION: {question}
"""


class QueryAnalyzerAgent(BaseAgent):
    """Turns a free-text question into a QueryPlan the graph can route on."""

    name = "query_analyzer"

    def plan_query(self, question: str) -> QueryPlan:
        """Classify the question. Never raises — an unclassifiable question just
        gets the full checklist, which is what the panel did before this existed."""
        try:
            data = self.invoke_json(CLASSIFY_PROMPT.format(question=question))
            intent = str(data.get("intent", DEFAULT_INTENT)).strip()
            reasoning = str(data.get("reasoning", "")).strip()
        except Exception as error:  # noqa: BLE001 - routing must never break the run
            logger.warning("Query classification failed, running everything: %s", error)
            plan = QueryPlan.for_intent(
                DEFAULT_INTENT, "Could not classify the question, so ran the full checklist."
            )
        else:
            plan = QueryPlan.for_intent(intent, reasoning)

        logger.info("Query intent: %s -> agents %s", plan.intent, plan.required_agents())
        self.trace({"question": question, "plan": plan.model_dump(mode="json")})
        return plan
