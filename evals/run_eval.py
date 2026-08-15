"""Runs the crew over 10 companies and checks three things about each report.

The three checks are the ones that matter for this project:

1. No blanks. A NaN reaching the report means a calculation failed quietly.
2. No invented numbers. Every figure in the report must come from something we
   calculated. This is the check that proves the LLM is not doing arithmetic.
3. All sections present. A missing section means the writer skipped part of the
   job.

Run it with:  python -m evals.run_eval
"""

import json
import math
import re
import sys

from src import config, graph
from src.tools import sourcing

log = config.get_logger(__name__)

# Ten US companies, picked so the checks are not all run against easy cases.
# Five are healthy, five are meant to set off the red-flag rules: Boeing has
# negative equity, Ford and AT&T carry heavy debt, Intel burns cash, and
# Walgreens has falling revenue. A run where nothing is flagged proves nothing.
TICKERS = ["AAPL", "MSFT", "JNJ", "KO", "PG",
           "F", "T", "INTC", "BA", "WBA"]

REQUIRED_SECTIONS = [
    "Executive summary", "Business quality", "Growth", "Profitability",
    "Cash generation", "Balance sheet", "Valuation", "Market context",
    "Recommendation", "Red flags",
]

def check_no_invented_numbers_detail(result):
    """Check 2 uses exactly the guard the reviewer uses, so the eval measures
    the real thing rather than a copy that can drift away from it."""
    unknown = sourcing.unsourced_numbers(result)
    return {"passed": not unknown, "detail": unknown[:15],
            "checked": len(sourcing.numbers_in(result.get("report", "")))}


def check_no_blanks(result):
    """Check 1: no NaN anywhere in the calculated values."""
    bad = []
    for where, values in (("fundamentals", result.get("fundamentals", {}).get("metrics", {})),
                          ("price", result.get("analysis", {}).get("kpis", {}))):
        for name, value in values.items():
            if isinstance(value, float) and math.isnan(value):
                bad.append(f"{where}.{name}")
    return {"passed": not bad, "detail": bad}


def check_no_invented_numbers(result):
    """Check 2: every number in the report traces back to a real source."""
    return check_no_invented_numbers_detail(result)


def check_sections_present(result):
    """Check 3: the report has every section it should."""
    report = result.get("report", "")
    missing = [name for name in REQUIRED_SECTIONS if f"## {name}" not in report]
    return {"passed": not missing, "detail": missing}


def evaluate(ticker, start_date, end_date):
    """Run one company and grade the report."""
    log.info("eval: %s", ticker)
    try:
        result = graph.run_crew(ticker, start_date, end_date)
    except Exception as error:
        return {"ticker": ticker, "crashed": str(error)}

    return {
        "ticker": ticker,
        "company": result.get("company"),
        "report": result.get("report", ""),
        "fundamentals": {"metrics": result.get("fundamentals", {}).get("metrics", {}),
                         "valuation": result.get("fundamentals", {}).get("valuation", {})},
        "analysis": {"kpis": result.get("analysis", {}).get("kpis", {}),
                     "benchmark": result.get("analysis", {}).get("benchmark")},
        "research": {"articles": result.get("research", {}).get("articles", []),
                     "social": result.get("research", {}).get("social", {}),
                     "news_sentiment": result.get("research", {}).get("news_sentiment")},
        "report_length": len(result.get("report", "")),
        "revisions": result.get("revision_count", 0),
        "errors": result.get("errors", []),
        "no_blanks": check_no_blanks(result),
        "no_invented_numbers": check_no_invented_numbers(result),
        "sections_present": check_sections_present(result),
    }


def main():
    start_date = "2023-01-01"
    end_date = "2026-08-13"
    tickers = sys.argv[1:] or TICKERS

    results = []
    for ticker in tickers:
        results.append(evaluate(ticker, start_date, end_date))

    print()
    print(f"{'ticker':16s} {'blanks':>8s} {'numbers':>9s} {'sections':>9s} {'revisions':>10s}")
    print("-" * 58)
    passed = 0
    for row in results:
        if row.get("crashed"):
            print(f"{row['ticker']:16s} CRASHED: {row['crashed'][:40]}")
            continue
        marks = [row["no_blanks"]["passed"], row["no_invented_numbers"]["passed"],
                 row["sections_present"]["passed"]]
        if all(marks):
            passed += 1
        print(f"{row['ticker']:16s} "
              f"{'pass' if marks[0] else 'FAIL':>8s} "
              f"{'pass' if marks[1] else 'FAIL':>9s} "
              f"{'pass' if marks[2] else 'FAIL':>9s} "
              f"{row['revisions']:>10d}")

    print("-" * 58)
    print(f"{passed} of {len(results)} reports passed all three checks.")

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUT_DIR / "eval_results.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, default=str)
    print(f"Full results written to {path}")


if __name__ == "__main__":
    main()
