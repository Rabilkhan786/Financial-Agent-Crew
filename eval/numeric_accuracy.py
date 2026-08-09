"""Objective metric: are the numbers actually correct?

This is where the panel's design wins by construction, and it needs no subjective
answer key. The Financial agent computes its figures directly from the data API, so
they match the source by definition. A single LLM asked for the same figures — even
with search — tends to *guess* and often states wrong numbers.

So we compare, for real companies:
  - PANEL numbers  = the API values (correct by construction -> 100%)
  - BASELINE numbers = what a single LLM states, checked against the same API values

The point isn't a "fair fight" — it's to quantify the reliability gap: computing
beats guessing. The LLM and searcher are injectable so this is testable offline.
"""

import json

from investpanel.agents.financial import FinancialAgent
from investpanel.llm.factory import get_llm
from investpanel.tools import search

# The metrics we check. These are unambiguous, single-number facts.
METRICS = ["revenue_growth", "profit_growth", "pe_ratio", "debt_to_equity"]

BASELINE_NUMBERS_PROMPT = """Using the search results below, give your best estimate of these
metrics for {company} ({ticker}). Return ONLY JSON with numeric values (or null if unknown):
  "revenue_growth": latest annual revenue growth in percent (e.g. 6.4),
  "profit_growth": latest annual net-income growth in percent,
  "pe_ratio": trailing P/E ratio,
  "debt_to_equity": total debt divided by shareholder equity

SEARCH RESULTS:
{results}
"""


def within_tolerance(stated, actual, rel_tol: float = 0.15, abs_floor: float = 1.0) -> bool:
    """True if the stated number is close enough to the actual API value.

    Uses a 15% relative tolerance, but for values near zero falls back to an
    absolute gap so tiny denominators don't make everything "wrong".
    """
    if stated is None:
        return False
    if abs(actual) < abs_floor:
        return abs(stated - actual) <= abs_floor
    return abs(stated - actual) / abs(actual) <= rel_tol


def ground_truth_numbers(ticker: str) -> dict[str, float]:
    """The real values from the data API (what the panel uses)."""
    findings = FinancialAgent().analyze(ticker)
    return {f.metric: f.value for f in findings if f.metric in METRICS}


def baseline_numbers(company: str, ticker: str, llm, searcher) -> dict:
    """What a single LLM (with search) states for the same metrics."""
    raw = searcher(f"{company} revenue growth profit growth P/E debt to equity", max_results=5)
    prompt = BASELINE_NUMBERS_PROMPT.format(
        company=company, ticker=ticker, results=json.dumps(raw.get("results", []), indent=2)
    )
    reply = llm.invoke(prompt)
    text = getattr(reply, "content", str(reply)).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def run(companies: list[tuple[str, str]], llm=None, searcher=None) -> dict:
    """Compare panel vs single-LLM numeric accuracy over (company, ticker) pairs."""
    llm = llm or get_llm()
    searcher = searcher or search.search_news

    total = 0
    baseline_correct = 0
    panel_correct = 0
    rows = []
    for company, ticker in companies:
        # Skip a company we can't fetch/query (e.g. a transient rate limit) instead
        # of crashing the whole run.
        try:
            actual = ground_truth_numbers(ticker)
            stated = baseline_numbers(company, ticker, llm, searcher)
        except Exception as error:  # noqa: BLE001 - skip and continue
            print(f"  SKIPPED {ticker}: {error}")
            continue
        for metric, real in actual.items():
            total += 1
            panel_correct += 1  # panel value IS the API value, by construction
            if within_tolerance(_as_float(stated.get(metric)), real):
                baseline_correct += 1
        rows.append({"ticker": ticker, "actual": actual, "baseline_stated": stated})
        print(f"  checked {ticker}: {len(actual)} metrics")

    summary = {
        "metrics_checked": total,
        "panel_accuracy": round(panel_correct / total, 3) if total else None,
        "baseline_accuracy": round(baseline_correct / total, 3) if total else None,
        "rows": rows,
    }
    return summary


def _as_float(value):
    """Coerce a stated value to float, or None if it isn't a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:

    from investpanel import config

    companies = [("Apple", "AAPL"), ("Microsoft", "MSFT"), ("Nvidia", "NVDA"),
                 ("Coca-Cola", "KO"), ("JPMorgan", "JPM")]
    print("Numeric-accuracy check (panel vs single LLM):")
    summary = run(companies)
    out = config.PROJECT_ROOT / "eval" / "results" / "numeric_accuracy.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nPanel accuracy:    {summary['panel_accuracy']}")
    print(f"Baseline accuracy: {summary['baseline_accuracy']}")
    print(f"(over {summary['metrics_checked']} metrics) -> wrote {out}")


if __name__ == "__main__":
    main()
