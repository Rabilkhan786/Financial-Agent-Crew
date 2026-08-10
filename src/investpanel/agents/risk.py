"""Risk specialist — computes risk from price data, no separate API, no LLM.

This is the agent that proves the "no redundant risk API" decision: it takes the
price history (fetched from Alpha Vantage) and runs the plain-Python math in
tools/volatility.py over it. Every number here is reproducible arithmetic, so the
Risk findings are as trustworthy and cheap as it gets. The LLM is not used at all.
"""

from investpanel import config
from investpanel.agents.base import BaseAgent
from investpanel.models.findings import RiskFinding
from investpanel.tools import alphavantage_client
from investpanel.tools.volatility import annualized_volatility, max_drawdown


def compute_risk_findings(prices: list[float], source: str) -> list[RiskFinding]:
    """Compute the risk findings from a chronological price list. Pure function.

    Returns no findings when the series has too little variation to measure.
    Some thinly-traded listings return the same stale close every day; that would
    compute to a confident-looking "0% volatility, 0% drawdown", which is worse
    than saying nothing. Reporting insufficient evidence is the honest answer.
    """
    if len(set(prices)) < config.MIN_DISTINCT_PRICES:
        return []

    vol = annualized_volatility(prices)
    drawdown = max_drawdown(prices)
    elevated = vol > config.HIGH_VOLATILITY_THRESHOLD
    computed_from = f"{len(prices)}-day close series, {source}"

    return [
        RiskFinding(
            metric="annualized_volatility",
            value=round(vol, 4),
            computed_from=computed_from,
            interpretation=(
                f"Annualized volatility is {vol*100:.0f}% — "
                f"{'elevated' if elevated else 'moderate'} versus a "
                f"{config.HIGH_VOLATILITY_THRESHOLD*100:.0f}% threshold."
            ),
        ),
        RiskFinding(
            metric="max_drawdown",
            value=round(drawdown, 4),
            computed_from=computed_from,
            interpretation=(
                f"Worst peak-to-trough drop in the window was {drawdown*100:.0f}%."
            ),
        ),
    ]


class RiskAgent(BaseAgent):
    """Fetches price history for a ticker and computes volatility and drawdown."""

    name = "risk"

    def analyze(self, ticker: str) -> list[RiskFinding]:
        data = alphavantage_client.get_daily_prices(ticker)
        prices = alphavantage_client.closing_prices(data)
        source = data.get("source", "AlphaVantage")
        findings = compute_risk_findings(prices, source)
        self.trace({"ticker": ticker.upper(), "findings": [f.model_dump(mode="json") for f in findings]})
        return findings
