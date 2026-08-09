"""GATE 0 check — proves the Phase 0 plumbing actually works end to end.

Run this after copying .env.example to .env and filling in your four keys:

    uv run python check_gate0.py

It does the five things GATE 0 requires and prints PASS / FAIL / SKIP for each:
  1. Reach Gemini and get a reply.
  2. FMP returns a real company profile.
  3. Alpha Vantage returns real price history.
  4. Tavily returns real search results.
  5. A local JSON trace file is written.

A check is SKIPPED (not failed) if its key is missing, so you can run it with a
partial .env and see how far you get. GATE 0 passes when all five say PASS.
"""

from investpanel import config
from investpanel.llm.factory import get_llm
from investpanel.tools import alphavantage_client, fmp_client, search
from investpanel.utils.tracing import init_langsmith, save_trace

TICKER = "AAPL"  # a large, well-covered company — reliable across all three APIs


def check_llm() -> tuple[str, str]:
    # Uses whatever provider LLM_PROVIDER selects (gemini/openai/anthropic/groq).
    provider = config.LLM_PROVIDER
    try:
        llm = get_llm()
    except RuntimeError as error:
        return "SKIP", str(error)  # the selected provider's key isn't set
    reply = llm.invoke("Reply with the single word: OK")
    text = getattr(reply, "content", str(reply)).strip()
    return "PASS", f"{provider} replied: {text[:40]!r}"


def check_fmp() -> tuple[str, str]:
    if not config.FMP_API_KEY:
        return "SKIP", "FMP_API_KEY not set"
    profile = fmp_client.get_company_profile(TICKER)
    return "PASS", f"{profile.get('companyName')} — sector {profile.get('sector')}"


def check_alphavantage() -> tuple[str, str]:
    if not config.ALPHAVANTAGE_API_KEY:
        return "SKIP", "ALPHAVANTAGE_API_KEY not set"
    data = alphavantage_client.get_daily_prices(TICKER)
    days = len(data.get("Time Series (Daily)", {}))
    return "PASS", f"got {days} days of prices for {TICKER}"


def check_tavily() -> tuple[str, str]:
    if not config.TAVILY_API_KEY:
        return "SKIP", "TAVILY_API_KEY not set"
    results = search.search_news(f"{TICKER} company news", max_results=3)
    count = len(results.get("results", []))
    return "PASS", f"got {count} search results"


def check_tracing() -> tuple[str, str]:
    # Tracing needs no key, so this should always pass.
    path = save_trace("gate0_check", {"note": "GATE 0 trace-write test", "ticker": TICKER})
    return "PASS", f"wrote {path.name}"


def main() -> None:
    init_langsmith()  # turns on LangSmith only if a key exists; never fails

    checks = [
        (f"1. LLM reachable ({config.LLM_PROVIDER})", check_llm),
        ("2. FMP profile", check_fmp),
        ("3. Alpha Vantage prices", check_alphavantage),
        ("4. Tavily search", check_tavily),
        ("5. Local trace file", check_tracing),
    ]

    print("\n=== GATE 0 CHECK ===\n")
    results = []
    for label, fn in checks:
        try:
            status, detail = fn()
        except Exception as error:  # noqa: BLE001 — we want to show any failure plainly
            status, detail = "FAIL", f"{type(error).__name__}: {error}"
        results.append(status)
        print(f"[{status:4}] {label:26} {detail}")

    passed = results.count("PASS")
    skipped = results.count("SKIP")
    failed = results.count("FAIL")
    print(f"\nSummary: {passed} passed, {skipped} skipped, {failed} failed.")
    if failed == 0 and skipped == 0:
        print("GATE 0 PASSED — all systems reachable.\n")
    elif failed == 0:
        print("No failures, but some checks were skipped (missing keys).\n")
    else:
        print("GATE 0 not yet passed — see FAIL lines above.\n")


if __name__ == "__main__":
    main()
