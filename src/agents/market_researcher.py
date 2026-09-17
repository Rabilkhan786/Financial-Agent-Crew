"""Research recent company news and retail sentiment."""

from src.components.logging import get_logger
from src.core import llm
from src.tools import news, social

log = get_logger(__name__)

PROMPT = """You are a market researcher.

Company: {company} ({ticker})
Sector: {sector}

Recent headlines:
{headlines}

Retail sentiment:
{social_sentiment}

{revision}

Write two short paragraphs:
1. What has happened around the company recently?
2. What is the current market mood?

Use only the supplied information. Do not predict the share price.
"""


def run(crew_state):
    """Fetch recent market context and summarize it with the LLM."""
    ticker = crew_state["ticker"]
    company = crew_state.get("company") or ticker
    profile = crew_state.get("profile") or {}

    articles = news.fetch_news(ticker)
    social_result = social.fetch_social_posts(ticker)

    headlines = "- no recent articles found"
    if articles:
        headlines = "\n".join(
            f"- [{item.get('published') or 'undated'}] {item.get('title')}"
            for item in articles
        )

    revision = ""
    if crew_state.get("revision_target") == "market_researcher":
        revision = "Reviewer feedback: " + crew_state.get("revision_reason", "")

    summary = llm.ask(
        PROMPT.format(
            company=company,
            ticker=ticker,
            sector=profile.get("sector") or "unknown",
            headlines=headlines,
            social_sentiment=social_result.get("social_sentiment"),
            revision=revision,
        )
    )

    message = (
        f"Collected {len(articles)} news articles and "
        f"{social_result.get('post_count', 0)} social posts."
    )
    log.info("%s: %s", ticker, message)

    return {
        "research": {
            "articles": articles,
            "social_sentiment": social_result.get("social_sentiment"),
            "summary": summary,
        },
        "conversation_log": [
            {"agent": "market_researcher", "message": message}
        ],
    }
