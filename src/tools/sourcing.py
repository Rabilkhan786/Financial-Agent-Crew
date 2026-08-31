"""Checks that every number in the report is real — either calculated or
found in a real headline.

If a number is made up, the report gets sent back.
"""

import math
import re

# Small counts, and the thresholds the red-flag rules themselves talk about.
ALWAYS_ALLOWED = {"0", "1", "2", "3", "4", "5", "50", "70", "100", "200", "2.0"}

# Index names contain digits that are not measurements.
INDEX_NAMES = ["S&P 500", "S&P500", "NIFTY 50", "NIFTY50", "Nasdaq 100",
               "FTSE 100", "BSE 500", "Magnificent Seven", "Fortune 500"]

# Dates are not figures, in either "2023-01-01" or "August 13, 2026" form.
DATE_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|(?:January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+\d{1,2},?\s+\d{4}")


def tidy(text):
    """Normalise text before pulling numbers out of it.

    Reports use narrow no-break spaces, and both reports and headlines write
    thousands with commas. "105,263" is one number, not a 105 and a 263. The
    same cleaning has to run on both sides or they will never match.
    """
    text = (text or "").replace("\u202f", " ").replace("\u00a0", " ").replace("\u2011", "-")
    return re.sub(r"(?<=\d),(?=\d)", "", text)


def numbers_in(report):
    """Every number written in the report, ignoring dates and index names."""
    text = DATE_PATTERN.sub(" ", tidy(report))
    for name in INDEX_NAMES:
        text = text.replace(name, " ")
    return re.findall(r"\d+(?:\.\d+)?", text)


def _remember(value, allowed):
    """Add one calculated value in every form it might be printed as."""
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


def allowed_numbers(crew_state):
    """Every number the report may legitimately use."""
    allowed = set(ALWAYS_ALLOWED)
    fundamentals = crew_state.get("fundamentals", {}) or {}
    analysis = crew_state.get("analysis", {}) or {}
    research = crew_state.get("research", {}) or {}

    for value in (fundamentals.get("metrics", {}) or {}).values():
        _remember(value, allowed)
    for value in (analysis.get("kpis", {}) or {}).values():
        _remember(value, allowed)

    for name in ("pe", "pb"):
        found = (fundamentals.get("valuation", {}) or {}).get(name)
        if found:
            for key in ("current", "median", "premium_pct"):
                _remember(found.get(key), allowed)

    against_index = analysis.get("benchmark")
    if against_index:
        for key in ("stock_return", "benchmark_return", "excess_return"):
            _remember(against_index.get(key), allowed)

    for column in (fundamentals.get("series", {}) or {}).values():
        try:
            for value in column.dropna().tolist():
                _remember(value, allowed)
        except AttributeError:
            pass

    # The post counts are worked out in Python, so "16 out of 30 posts" is a
    # calculated figure like any other.
    social = research.get("social", {}) or {}
    for value in (social.get("tally", {}) or {}).values():
        _remember(value, allowed)
    _remember(social.get("post_count"), allowed)

    sentiment = research.get("news_sentiment") or {}
    _remember(sentiment.get("average_score"), allowed)
    _remember(sentiment.get("articles_scored"), allowed)

    # A figure quoted from a headline we fetched is sourced, not invented.
    for article in research.get("articles", []) or []:
        text = tidy(f"{article.get('title', '')} {article.get('summary', '')}")
        allowed.update(re.findall(r"\d+(?:\.\d+)?", text))

    for year in range(2015, 2036):
        allowed.add(str(year))
    return allowed


def unsourced_numbers(crew_state, report=None):
    """Numbers in the report that trace back to nothing. Empty list is good."""
    text = report if report is not None else crew_state.get("report", "")
    allowed = allowed_numbers(crew_state)
    unknown = []
    for written in numbers_in(text):
        if written.lstrip("-") not in allowed and written not in unknown:
            unknown.append(written)
    return unknown
