"""Manager — reads the question and sets the scope for everyone else.

It does three things: work out which company and ticker the question is about,
find 2-3 *real* competitors (grounded in a live search, never guessed from the
model's memory), and get a company description for checklist Q1 straight from
FMP's profile (a real source). Everything it produces is a ResearchScope, the
Pydantic contract the rest of the panel consumes.
"""

import json

from investpanel.agents.base import BaseAgent
from investpanel.models.scope import ResearchScope
from investpanel.tools import fmp_client, search

PARSE_PROMPT = """A user asked this investment question. Identify the subject company.
Return ONLY JSON:
  "company": the company name,
  "ticker": its stock ticker in capitals (best guess if not stated),
  "time_window": the time frame implied, else "last 12 months",
  "priority_focus": the specific concern the question emphasises, else null

QUESTION: {question}
"""

COMPETITORS_PROMPT = """From these REAL search results about {company}'s competitors,
list 2-3 actual competitor companies. Use ONLY names that appear in the results —
do not add companies from your own memory.

Return ONLY JSON: {{"competitors": [{{"name": "...", "ticker": "..."}}, ...]}}

SEARCH RESULTS:
{results}
"""


class ManagerAgent(BaseAgent):
    """Turns a free-text question into a structured ResearchScope."""

    name = "manager"

    def plan(self, question: str) -> ResearchScope:
        parsed = self.invoke_json(PARSE_PROMPT.format(question=question))
        company = parsed.get("company") or question
        ticker = (parsed.get("ticker") or "").upper() or None

        scope = ResearchScope(
            company=company,
            ticker=ticker,
            competitors=self._find_competitors(company),
            time_window=parsed.get("time_window") or "last 12 months",
            priority_focus=parsed.get("priority_focus"),
        )
        self.trace({"question": question, "scope": scope.model_dump(mode="json")})
        return scope

    def _find_competitors(self, company: str) -> list[str]:
        """Find competitors via a real search, then extract names from the results.

        Grounding this in fetched search text (not the model's memory) is what makes
        the peer list defensible — the spec's "found via search, never guessed" rule.
        """
        raw = search.search_news(f"{company} main competitors and industry peers", max_results=5)
        results = raw.get("results", [])
        if not results:
            return []
        data = self.invoke_json(
            COMPETITORS_PROMPT.format(company=company, results=json.dumps(results, indent=2))
        )
        competitors = data.get("competitors", [])[:3]
        # Prefer the ticker (the Financial agent needs it); fall back to the name.
        return [(c.get("ticker") or c.get("name")) for c in competitors if c.get("ticker") or c.get("name")]

    def company_description(self, ticker: str | None) -> str:
        """Company description for checklist Q1, taken from FMP's profile (a source)."""
        if not ticker:
            return ""
        try:
            profile = fmp_client.get_company_profile(ticker)
        except Exception:  # noqa: BLE001 - a missing description must not break the run
            return ""
        return (profile.get("description") or "")[:600]
