"""GATE 3 demo — print each specialist's findings for one company, with sources.

Run after your .env keys are in place:

    uv run python demo_gate3.py AAPL

It runs the Financial, News, and Risk specialists independently (no manager, no
analyst yet) and prints their raw findings side by side, each with its source —
which is exactly what GATE 3 asks to see.
"""

import sys

from investpanel.agents.financial import FinancialAgent
from investpanel.agents.news import NewsAgent
from investpanel.agents.risk import RiskAgent


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    company = sys.argv[2] if len(sys.argv) > 2 else ticker

    print(f"\n=== SPECIALIST FINDINGS FOR {ticker.upper()} ===\n")

    print("--- FINANCIAL (from FMP, computed in Python) ---")
    for f in FinancialAgent().analyze(ticker):
        flag = "healthy" if f.healthy else "unhealthy"
        print(f"  [{flag:9}] {f.metric:20} {f.value} {f.unit}  ({f.period})")
        print(f"              {f.interpretation}   source: {f.source}")

    print("\n--- RISK (computed in Python from price history) ---")
    for f in RiskAgent().analyze(ticker):
        print(f"  {f.metric:22} {f.value}")
        print(f"              {f.interpretation}   computed_from: {f.computed_from}")

    print("\n--- NEWS (summarized from really-fetched articles) ---")
    for f in NewsAgent().analyze(company):
        print(f"  [{f.relevance:6}] {f.headline}  ({f.published_date})")
        print(f"              {f.summary}")
        print(f"              source: {f.source_url}   tag: {f.checklist_question}")

    print("\nEach finding above carries a source — the no-unsourced-facts rule.\n")


if __name__ == "__main__":
    main()
