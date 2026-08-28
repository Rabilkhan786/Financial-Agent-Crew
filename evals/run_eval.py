"""Runs the crew over 10 companies and checks three things about each report.

The three checks are the ones that matter for this project:

1. No blanks. A NaN reaching the report means a calculation failed quietly.
2. No invented numbers. Every figure in the report must come from something we
   calculated. This is the check that proves the LLM is not doing arithmetic.
3. All sections present. A missing section means the writer skipped part of the
   job.

Each company also gets one of four classifications, not just pass/fail:
PASS, FAIL, DATA_UNAVAILABLE (Yahoo had nothing for the ticker), or
PROVIDER_LIMIT (the model did not answer - almost always the free tier's daily
or per-minute token limit). The three checks above measure report quality;
classify() is what keeps a provider outage from being reported as if it were
a bug in the crew.

Run it with:  python -m evals.run_eval
                 or on a subset:  python -m evals.run_eval AAPL MSFT
"""

import json
import math
import sys

from src import config, graph
from src.agents.report_writer import STUB_REPORT_MARKER
from src.tools import sourcing

log = config.get_logger(__name__)

# Ten US companies, picked so the checks are not all run against easy cases.
# Five are healthy; five are meant to set off the red-flag rules. Boeing is
# heavily borrowed with thin interest cover, Ford and AT&T carry heavy debt,
# Intel burns cash, and Lumen manages negative equity, high leverage, thin
# cover and falling revenue at once. A run where nothing is flagged proves
# nothing.
#
# Walgreens (WBA) used to be here and was dropped: it was taken private, so
# Yahoo returns no data at all and its "failure" was an empty report rather
# than anything the checks were meant to find.
TICKERS = ["AAPL", "MSFT", "JNJ", "KO", "PG",
           "F", "T", "INTC", "BA", "LUMN"]

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


def classify(result):
    """PASS, FAIL, DATA_UNAVAILABLE, or PROVIDER_LIMIT.

    A run that crashed, a company Yahoo has no data for, and a report the model
    never answered are three different problems, and none of them is the same
    as a report that came back complete but wrong. Folding all four into a
    single FAIL - which the three checks above would otherwise do - would hide
    exactly the distinction that matters when reading these results: is this
    the crew's fault, or the free tier's.
    """
    if result.get("crashed"):
        return "FAIL"

    if STUB_REPORT_MARKER in (result.get("report") or ""):
        # The model never answered - almost always the free tier's daily or
        # per-minute token limit. Checked first: even when no statement or
        # price data was fetched either, a stub report is the more specific,
        # more useful thing to say happened.
        return "PROVIDER_LIMIT"

    no_metrics = not result.get("fundamentals", {}).get("metrics")
    no_kpis = not result.get("analysis", {}).get("kpis")
    if no_metrics and no_kpis:
        # Neither the statements nor the prices came back - Yahoo had nothing
        # for this ticker. Not a report-writing problem at all.
        return "DATA_UNAVAILABLE"

    marks = [result["no_blanks"]["passed"], result["no_invented_numbers"]["passed"],
             result["sections_present"]["passed"]]
    return "PASS" if all(marks) else "FAIL"


def evaluate(ticker, start_date, end_date):
    """Run one company and grade the report."""
    log.info("eval: %s", ticker)
    try:
        result = graph.run_crew(ticker, start_date, end_date)
    except Exception as error:
        return {"ticker": ticker, "crashed": str(error), "classification": "FAIL"}

    row = {
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
    row["classification"] = classify(row)
    return row


def main():
    start_date = "2023-01-01"
    end_date = "2026-08-13"
    tickers = sys.argv[1:] or TICKERS

    results = []
    for ticker in tickers:
        results.append(evaluate(ticker, start_date, end_date))

    print()
    print(f"{'ticker':14s} {'blanks':>8s} {'numbers':>9s} {'sections':>9s} "
          f"{'revisions':>10s} {'status':>15s}")
    print("-" * 74)
    counts = {"PASS": 0, "FAIL": 0, "DATA_UNAVAILABLE": 0, "PROVIDER_LIMIT": 0}
    for row in results:
        status = row["classification"]
        counts[status] += 1
        if row.get("crashed"):
            print(f"{row['ticker']:14s} CRASHED: {row['crashed'][:44]:44s} {status:>15s}")
            continue
        marks = [row["no_blanks"]["passed"], row["no_invented_numbers"]["passed"],
                 row["sections_present"]["passed"]]
        print(f"{row['ticker']:14s} "
              f"{'pass' if marks[0] else 'FAIL':>8s} "
              f"{'pass' if marks[1] else 'FAIL':>9s} "
              f"{'pass' if marks[2] else 'FAIL':>9s} "
              f"{row['revisions']:>10d} "
              f"{status:>15s}")

    print("-" * 74)
    print(f"{counts['PASS']} PASS, {counts['FAIL']} FAIL, "
          f"{counts['DATA_UNAVAILABLE']} DATA_UNAVAILABLE, "
          f"{counts['PROVIDER_LIMIT']} PROVIDER_LIMIT, out of {len(results)}.")
    if counts["PROVIDER_LIMIT"]:
        print("PROVIDER_LIMIT means the model did not answer for that company - "
              "almost always the free tier's daily or per-minute token limit, "
              "not a defect in the crew. See README.md's 'Known limit' section.")

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUT_DIR / "eval_results.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, default=str)
    print(f"Full results written to {path}")


if __name__ == "__main__":
    main()
