"""Financial specialist — real fundamentals, computed in plain Python.

Design choice worth defending: the numbers here are computed directly from FMP's
statements in Python, never written by the LLM. That means a figure like "revenue
growth = 12%" traces straight back to an API field and can't be hallucinated —
the no-unsourced-facts rule, enforced by construction. The LLM is not involved in
producing any number; the ``interpretation`` sentence is templated from the value
and the healthy/not-healthy check. Each metric maps to one of the checklist
questions (Q2-Q6, Q10).

FMP field names occasionally vary; where that's likely we read with a couple of
fallbacks. If a metric can't be computed (missing data, divide-by-zero) we skip
it rather than invent a value.
"""

from investpanel import config
from investpanel.agents.base import BaseAgent
from investpanel.models.findings import FinancialFinding
from investpanel.tools import fmp_client


def _pick(row: dict, *names: str):
    """Return the first present, non-null field from a row, or None."""
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return None


def _safe_div(numerator, denominator):
    """Divide, returning None if we can't (missing data or zero denominator)."""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _finding(metric, value, unit, period, source, healthy, interpretation) -> FinancialFinding:
    return FinancialFinding(
        metric=metric,
        value=round(float(value), 4),
        unit=unit,
        period=period,
        source=source,
        interpretation=interpretation,
        healthy=healthy,
    )


def compute_findings(
    income: list[dict],
    balance: list[dict],
    cashflow: list[dict],
    ratios: dict,
    source: str,
) -> list[FinancialFinding]:
    """Turn raw FMP statements into a list of FinancialFindings. Pure function.

    Kept separate from the API calls so it can be unit-tested with fixture data
    and no network. Only metrics we can actually compute are returned.
    """
    findings: list[FinancialFinding] = []
    latest = income[0]
    period = str(_pick(latest, "calendarYear", "date") or "latest")

    # Q2 revenue growth (needs two years).
    if len(income) >= 2:
        rev_now = _pick(income[0], "revenue")
        rev_prev = _pick(income[1], "revenue")
        growth = _safe_div((rev_now - rev_prev) if rev_now and rev_prev else None, rev_prev)
        if growth is not None:
            findings.append(_finding(
                "revenue_growth", growth * 100, "percent_yoy", period, source,
                healthy=growth > 0,
                interpretation=f"Revenue {'grew' if growth > 0 else 'fell'} {growth*100:.1f}% year over year.",
            ))

        # Q3 profit growth.
        ni_now = _pick(income[0], "netIncome")
        ni_prev = _pick(income[1], "netIncome")
        pgrowth = _safe_div((ni_now - ni_prev) if ni_now and ni_prev else None, abs(ni_prev) if ni_prev else None)
        if pgrowth is not None:
            findings.append(_finding(
                "profit_growth", pgrowth * 100, "percent_yoy", period, source,
                healthy=pgrowth > 0,
                interpretation=f"Net income {'grew' if pgrowth > 0 else 'fell'} {pgrowth*100:.1f}% year over year.",
            ))

    # Q4 operating cash flow (healthy if positive and roughly backing net income).
    ocf = _pick(cashflow[0], "operatingCashFlow", "netCashProvidedByOperatingActivities") if cashflow else None
    if ocf is not None:
        ni_now = _pick(income[0], "netIncome")
        backs_profit = ni_now is None or ocf >= 0.8 * ni_now
        findings.append(_finding(
            "operating_cash_flow", ocf, "currency", period, source,
            healthy=ocf > 0 and backs_profit,
            interpretation=(
                "Operating cash flow is positive and broadly backs reported profit."
                if ocf > 0 and backs_profit else
                "Operating cash flow is weak relative to reported profit — a quality flag."
            ),
        ))

    # Q5 debt-to-equity and interest coverage.
    if balance:
        debt = _pick(balance[0], "totalDebt")
        equity = _pick(balance[0], "totalStockholdersEquity", "totalEquity")
        d_to_e = _safe_div(debt, equity)
        if d_to_e is not None:
            findings.append(_finding(
                "debt_to_equity", d_to_e, "ratio", period, source,
                healthy=d_to_e < config.HEALTHY_DEBT_TO_EQUITY_MAX,
                interpretation=f"Debt-to-equity is {d_to_e:.2f}x.",
            ))

        op_income = _pick(income[0], "operatingIncome")
        interest = _pick(income[0], "interestExpense")
        coverage = _safe_div(op_income, interest)
        if coverage is not None:
            findings.append(_finding(
                "interest_coverage", coverage, "times", period, source,
                healthy=coverage > config.HEALTHY_INTEREST_COVERAGE_MIN,
                interpretation=f"Operating income covers interest {coverage:.1f}x.",
            ))

        # Q6 ROCE and ROE.
        assets = _pick(balance[0], "totalAssets")
        cur_liab = _pick(balance[0], "totalCurrentLiabilities")
        capital_employed = (assets - cur_liab) if (assets is not None and cur_liab is not None) else None
        roce = _safe_div(op_income, capital_employed)
        if roce is not None:
            findings.append(_finding(
                "roce", roce, "ratio", period, source,
                healthy=roce > config.HEALTHY_ROCE_MIN,
                interpretation=f"Return on capital employed is {roce*100:.1f}%.",
            ))

        ni_now = _pick(income[0], "netIncome")
        roe = _safe_div(ni_now, equity)
        if roe is not None:
            findings.append(_finding(
                "roe", roe, "ratio", period, source,
                healthy=roe > config.HEALTHY_ROE_MIN,
                interpretation=f"Return on equity is {roe*100:.1f}%.",
            ))

    # Q10 valuation: P/E, P/B, and a PEG-like valuation-vs-growth check.
    pe = _pick(ratios, "peRatioTTM", "priceEarningsRatioTTM")
    if pe is not None:
        findings.append(_finding(
            "pe_ratio", pe, "ratio", "TTM", source,
            healthy=0 < pe < config.HEALTHY_PE_MAX,
            interpretation=f"Price-to-earnings is {pe:.1f}x (trailing).",
        ))
    pb = _pick(ratios, "priceToBookRatioTTM", "pbRatioTTM")
    if pb is not None:
        findings.append(_finding(
            "pb_ratio", pb, "ratio", "TTM", source,
            healthy=0 < pb < config.HEALTHY_PB_MAX,
            interpretation=f"Price-to-book is {pb:.1f}x.",
        ))
    # PEG-like: only meaningful when both P/E and positive profit growth exist.
    profit_growth_pct = next((f.value for f in findings if f.metric == "profit_growth"), None)
    if pe is not None and profit_growth_pct and profit_growth_pct > 0:
        peg = pe / profit_growth_pct
        findings.append(_finding(
            "valuation_vs_growth", peg, "peg", "TTM", source,
            healthy=peg < config.HEALTHY_PEG_MAX,
            interpretation=f"Valuation-vs-growth (PEG-like) is {peg:.2f}.",
        ))

    return findings


class FinancialAgent(BaseAgent):
    """Fetches FMP statements for a ticker and computes the checklist metrics."""

    name = "financial"

    def analyze(self, ticker: str) -> list[FinancialFinding]:
        """Return the list of FinancialFindings for one ticker, each sourced."""
        source = f"FMP statements for {ticker.upper()}"
        income = fmp_client.get_income_statement(ticker, limit=2)
        balance = fmp_client.get_balance_sheet(ticker, limit=1)
        cashflow = fmp_client.get_cash_flow(ticker, limit=1)
        ratios = fmp_client.get_ratios_ttm(ticker)
        findings = compute_findings(income, balance, cashflow, ratios, source)
        self.trace({"ticker": ticker.upper(), "findings": [f.model_dump(mode="json") for f in findings]})
        return findings

    def peer_metric_table(self, tickers: list[str]) -> dict[str, dict[str, float]]:
        """Build metric -> {ticker: value} for the target plus its competitors.

        Feeds the Report's peer_comparison. Reuses ``analyze`` for each ticker, so
        every peer number is computed the exact same way as the target's.
        """
        table: dict[str, dict[str, float]] = {}
        for ticker in tickers:
            for finding in self.analyze(ticker):
                table.setdefault(finding.metric, {})[ticker.upper()] = finding.value
        return table
