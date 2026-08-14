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

from src import config, formatting, graph

log = config.get_logger(__name__)

# A mix of US and Indian companies, large and small, healthy and struggling,
# so the checks are not all run against easy cases.
TICKERS = ["AAPL", "MSFT", "KO", "F", "INTC",
           "RELIANCE.NS", "TATAELXSI.NS", "INFY.NS", "ITC.NS", "YESBANK.NS"]

REQUIRED_SECTIONS = [
    "Executive summary", "Business quality", "Growth", "Profitability",
    "Cash generation", "Balance sheet", "Valuation", "Market context",
    "Recommendation", "Red flags",
]

# Numbers that are always allowed in the text: years, small counts, and the
# percentages the rules themselves talk about.
ALWAYS_ALLOWED = {"0", "1", "2", "3", "4", "5", "50", "70", "100", "200", "2.0"}


def numbers_we_calculated(result):
    """Every number the report is allowed to use, as text.

    Each value is written out several ways because the model may print 0.18 as
    18%, 18.0% or 0.18 and all of those are honest.
    """
    allowed = set(ALWAYS_ALLOWED)

    def remember(value):
        if value is None or isinstance(value, bool):
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if math.isnan(number):
            return
        for text in (f"{number:.0f}", f"{number:.1f}", f"{number:.2f}",
                     f"{number * 100:.0f}", f"{number * 100:.1f}",
                     f"{abs(number):.1f}", f"{abs(number) * 100:.1f}",
                     f"{number / 1_000_000:.1f}", f"{number / 1_000_000_000:.2f}",
                     f"{number / 1_000_000_000:.1f}"):
            allowed.add(text.lstrip("-"))

    fundamentals = result.get("fundamentals", {})
    analysis = result.get("analysis", {})

    for value in fundamentals.get("metrics", {}).values():
        remember(value)
    for value in analysis.get("kpis", {}).values():
        remember(value)
    for name in ("pe", "pb"):
        found = fundamentals.get("valuation", {}).get(name)
        if found:
            remember(found.get("current"))
            remember(found.get("median"))
            remember(found.get("premium_pct"))
    against_index = analysis.get("benchmark")
    if against_index:
        for key in ("stock_return", "benchmark_return", "excess_return"):
            remember(against_index.get(key))
    for column in fundamentals.get("series", {}).values():
        for value in column.dropna().tolist():
            remember(value)

    # The social post counts are worked out in Python too, so "16 out of 30
    # posts" is a calculated figure like any other.
    research = result.get("research", {})
    for value in (research.get("social", {}).get("tally", {}) or {}).values():
        remember(value)
    remember(research.get("social", {}).get("post_count"))

    # A number quoted from a headline we actually fetched is sourced, not
    # invented. "$20 billion capital raise" is fine if a real article said it.
    for article in research.get("articles", []):
        text = f"{article.get('title', '')} {article.get('summary', '')}"
        for written in re.findall(r"\d+(?:\.\d+)?", text):
            allowed.add(written)

    # Years are always fine to mention.
    for year in range(2015, 2036):
        allowed.add(str(year))
    return allowed


# Dates are not figures. Both "2023-01-01" and "August 13, 2026" must not be
# read as the numbers 01, 13 and so on.
DATE_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|(?:January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+\d{1,2},?\s+\d{4}")


def numbers_in(report):
    """Every number written in the report, ignoring dates."""
    without_dates = DATE_PATTERN.sub(" ", report or "")
    return re.findall(r"\d+(?:\.\d+)?", without_dates)


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
    """Check 2: every number in the report traces back to a calculation."""
    allowed = numbers_we_calculated(result)
    unknown = []
    for written in numbers_in(result.get("report", "")):
        if written.lstrip("-") not in allowed:
            unknown.append(written)
    return {"passed": not unknown, "detail": sorted(set(unknown))[:15],
            "checked": len(numbers_in(result.get("report", "")))}


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
        "research": {"articles": result.get("research", {}).get("articles", []),
                     "social": result.get("research", {}).get("social", {})},
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
