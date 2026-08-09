"""News specialist — finds real articles and summarizes them, with sources.

This is the agent where the no-unsourced-facts rule bites hardest, so it is built
so a claim can only exist if it came from a page we actually fetched: we search,
download each article's text, and the LLM may only summarize that text. The
``source_url`` on every NewsFinding is the URL we really fetched — never a URL the
model made up — and the Pydantic model refuses to build without one. Articles we
can't fetch, or that lack a usable date, are skipped rather than guessed.
"""

from datetime import date

from investpanel.agents.base import BaseAgent
from investpanel.models.findings import NewsFinding
from investpanel.tools import fetch, search

# The LLM only writes the prose summary and tags — never the URL or the facts'
# existence. We cap the text so the prompt stays small.
SUMMARY_PROMPT = """Summarize this article about {company} for an investment analyst.
Use ONLY the article text below — do not add outside knowledge.

Return ONLY a JSON object:
  "summary": 2-3 sentences in your own words (do not copy sentences),
  "relevance": one of "high", "medium", "low",
  "checklist_question": one of "moat", "management", "risk", or null,
  "published_date": the article's date as "YYYY-MM-DD" ONLY if the text states one, else null

ARTICLE TITLE: {title}
ARTICLE TEXT:
{text}
"""


class NewsAgent(BaseAgent):
    """Searches for recent news and returns summarized, sourced findings."""

    name = "news"

    def analyze(self, company: str, max_articles: int = 3, focus: str | None = None) -> list[NewsFinding]:
        query = f"{company} {focus}" if focus else f"{company} company news outlook risks"
        raw = search.search_news(query, max_results=max_articles + 2)
        results = raw.get("results", [])

        findings: list[NewsFinding] = []
        for result in results:
            if len(findings) >= max_articles:
                break
            finding = self._finding_from_result(company, result)
            if finding is not None:
                findings.append(finding)

        self.trace({"company": company, "findings": [f.model_dump(mode="json") for f in findings]})
        return findings

    def _finding_from_result(self, company: str, result: dict) -> NewsFinding | None:
        """Fetch one article and summarize it, or return None if we can't source it."""
        url = result.get("url")
        if not url:
            return None
        try:
            text = fetch.fetch_article_text(url)
        except Exception:  # noqa: BLE001 - intentional: skip any article we can't fetch, for any reason
            # Couldn't fetch/extract -> we have no real source, so we skip it.
            return None

        prompt = SUMMARY_PROMPT.format(
            company=company,
            title=result.get("title", ""),
            text=text[:4000],
        )
        data = self.invoke_json(prompt)

        published = self._resolve_date(result.get("published_date"), data.get("published_date"))
        if published is None:
            # No trustworthy date -> skip rather than invent one.
            return None

        relevance = data.get("relevance", "medium")
        if relevance not in ("high", "medium", "low"):
            relevance = "medium"

        return NewsFinding(
            headline=result.get("title") or f"{company} news",
            summary=data.get("summary", "").strip(),
            source_url=url,  # the URL we actually fetched — the real source
            published_date=published,
            relevance=relevance,
            checklist_question=data.get("checklist_question"),
        )

    @staticmethod
    def _resolve_date(from_search, from_model) -> date | None:
        """Prefer the search result's date, then a date the article itself stated."""
        for candidate in (from_search, from_model):
            if not candidate:
                continue
            try:
                # Handle both "YYYY-MM-DD" and longer ISO timestamps.
                return date.fromisoformat(str(candidate)[:10])
            except ValueError:
                continue
        return None
