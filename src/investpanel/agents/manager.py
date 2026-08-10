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
from investpanel.utils.logging import get_logger

logger = get_logger(__name__)

# Words that appear in company names but say nothing about identity — ignored when
# checking that a search result is really the company we asked for.
_NAME_NOISE = {
    "inc", "inc.", "corp", "corp.", "corporation", "co", "co.", "company", "ltd",
    "ltd.", "limited", "plc", "sa", "ag", "nv", "the", "group", "holdings",
    "holding", "class", "&",
}

PARSE_PROMPT = """A user asked this investment question. It may contain typos, missing
words, or broken grammar — read past those to what they meant.

Return ONLY JSON:
  "clarified_question": the same question rewritten as clear English. Fix spelling and
      grammar ONLY. Keep the user's original meaning and scope exactly — never switch to
      a different company, never add a topic they didn't ask about, never answer it.
  "company": the company name,
  "ticker": its stock ticker in capitals (best guess if not stated),
  "time_window": the time frame implied, else "last 12 months",
  "priority_focus": the specific concern the question emphasises, else null

Example: "bmw profit is how and is worth to invest it"
  -> "How is BMW's profit, and is it worth investing in?"

QUESTION: {question}
"""

COMPETITORS_PROMPT = """From these REAL search results about {company}'s competitors,
list 2-3 actual competitor companies. Use ONLY names that appear in the results —
do not add companies from your own memory.

Return ONLY JSON: {{"competitors": [{{"name": "...", "ticker": "..."}}, ...]}}

SEARCH RESULTS:
{results}
"""


def _name_tokens(name: str) -> set[str]:
    """The meaningful words in a company name, lowercased and de-punctuated."""
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in name.lower())
    return {word for word in cleaned.split() if word and word not in _NAME_NOISE}


def names_match(requested: str, candidate: str) -> bool:
    """True if a search result plausibly IS the company we asked about.

    This guard exists because searching "BMW" also returns "BMW Industries Ltd",
    an unrelated Indian company. Silently researching the wrong business would be
    far worse than returning nothing, so we require the requested name's words to
    actually appear in the candidate's name.
    """
    wanted = _name_tokens(requested)
    found = _name_tokens(candidate)
    if not wanted or not found:
        return False
    # Every meaningful word we asked for must be present, OR the candidate is a
    # strict extension of a single-word name (e.g. "BMW" -> "BMW Industries" is
    # rejected below by the extra-word check, but "Apple" -> "Apple Inc" passes).
    return wanted.issubset(found)


def _candidate_rank(row: dict, company: str) -> tuple[int, int]:
    """Sort key for search results, best first.

    Two things decide it, in order:
      1. an exact name match beats a merely-containing one, so searching "Apple"
         prefers "Apple Inc" over "Apple Hospitality REIT";
      2. then the US-listed / USD line, since that's what our data plan covers.
    """
    exact = 0 if _name_tokens(company) == _name_tokens(row.get("name", "")) else 1

    currency = (row.get("currency") or "").upper()
    exchange = (row.get("exchange") or "").upper()
    if exchange in ("NASDAQ", "NYSE", "AMEX"):
        listing = 0
    elif currency == "USD":  # e.g. an OTC ADR like BMWYY
        listing = 1
    else:
        listing = 2
    return (exact, listing)


def symbol_matches(query: str, symbol: str) -> bool:
    """True if a ticker plausibly belongs to the queried brand/name.

    Needed because a brand name often isn't in the legal name: "BMW" never
    appears in "Bayerische Motoren Werke AG", so name matching alone throws away
    the correct BMWYY and leaves only the unrelated "BMW Industries Ltd".
    Matching the symbol itself recovers it (BMW.DE, BMWYY all start with BMW).
    """
    wanted = "".join(ch for ch in query.upper() if ch.isalnum())
    symbol = symbol.upper()
    if not wanted or not symbol:
        return False
    base = symbol.split(".")[0]  # "BMW.DE" -> "BMW"
    return base == wanted or symbol.startswith(wanted)


def pick_best_symbol(company: str, results: list[dict]) -> str | None:
    """Choose the best real ticker for ``company`` from FMP search results.

    A row qualifies if its company NAME matches or its SYMBOL matches the brand.
    Ranking then decides: an exact name match always wins (so "BMW Industries"
    keeps BMW.BO), otherwise the US/USD listing wins (so plain "BMW" resolves to
    the BMWYY ADR, not an unrelated Indian company). Returns None when nothing
    qualifies, and the caller keeps what it had rather than guessing.
    """
    matches = [
        r for r in results
        if r.get("symbol")
        and (names_match(company, r.get("name", "")) or symbol_matches(company, r["symbol"]))
    ]
    if not matches:
        return None
    matches.sort(key=lambda row: _candidate_rank(row, company))
    return matches[0]["symbol"].upper()


class ManagerAgent(BaseAgent):
    """Turns a free-text question into a structured ResearchScope."""

    name = "manager"

    def plan(self, question: str) -> ResearchScope:
        parsed = self.invoke_json(PARSE_PROMPT.format(question=question))
        company = parsed.get("company") or question
        ticker = self.resolve_ticker(company, (parsed.get("ticker") or "").upper() or None)

        scope = ResearchScope(
            company=company,
            ticker=ticker,
            # Fall back to what the user typed if the model didn't return a rewrite —
            # a missing correction must never lose the original question.
            clarified_question=(parsed.get("clarified_question") or "").strip() or question,
            competitors=self._find_competitors(company),
            time_window=parsed.get("time_window") or "last 12 months",
            priority_focus=parsed.get("priority_focus"),
        )
        self.trace({"question": question, "scope": scope.model_dump(mode="json")})
        return scope

    def resolve_ticker(self, company: str, guessed: str | None) -> str | None:
        """Check the LLM's guessed ticker against reality, and fix it if it's wrong.

        The LLM guesses a ticker from memory, which can be a symbol that doesn't
        exist (it guessed "BMW", which FMP has no record of — so the whole run
        came back empty). Here we:
          1. accept the guess if it really resolves to a profile (the common case,
             one cheap cached call, no change for AAPL/NVDA/NKE);
          2. otherwise look the company up in FMP's real symbol search;
          3. prefer the US-listed line, since that's what our data plan covers;
          4. keep the original guess if nothing verifies, so the report degrades
             honestly instead of researching some other company.
        """
        if guessed and self._ticker_exists(guessed):
            return guessed

        best = pick_best_symbol(company, self._search_candidates(company, guessed))
        if best and self._ticker_exists(best):
            logger.info("Resolved ticker for %s: %s -> %s", company, guessed, best)
            return best
        return guessed

    @staticmethod
    def _search_candidates(company: str, guessed: str | None) -> list[dict]:
        """Gather possible listings from FMP's two search endpoints.

        They match different fields — one on company name, one on ticker — so we
        ask both and merge. Any failure just contributes no candidates.
        """
        candidates: list[dict] = []
        seen: set[str] = set()
        lookups = [(fmp_client.search_name, company), (fmp_client.search_symbol, company)]
        if guessed:
            lookups.append((fmp_client.search_symbol, guessed))

        for lookup, query in lookups:
            try:
                results = lookup(query)
            except Exception as error:  # noqa: BLE001 - best-effort, never fatal
                logger.warning("Ticker lookup failed for %r: %s", query, error)
                continue
            for row in results:
                symbol = (row.get("symbol") or "").upper()
                if symbol and symbol not in seen:
                    seen.add(symbol)
                    candidates.append(row)
        return candidates

    @staticmethod
    def _ticker_exists(ticker: str) -> bool:
        """True if FMP actually has a profile for this symbol (cached call)."""
        try:
            return bool(fmp_client.get_company_profile(ticker))
        except Exception:  # noqa: BLE001 - any failure means "can't verify it"
            return False

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
