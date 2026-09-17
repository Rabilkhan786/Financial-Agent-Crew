"""Research recent company news and retail sentiment."""

from src.components.logging import get_logger
from src.core import llm
from src.tools import market_data, news, social

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
    """Fetch market context and summarize it with the LLM."""
    ticker = crew_state["ticker"]
    profile = market_data.fetch_profile(ticker)
    company = crew_state.get("company") or profile.get("name") or ticker

    news_result = news.fetch_news(ticker)
    social_result = social.fetch_social_posts(ticker)

    articles = news_result.get("articles") or []
    if articles:
        headlines = "\n".join(
            f"- [{item.get('published') or 'undated'}] {item.get('title')}"
            for item in articles
        )
    else:
        headlines = "- no recent articles found"

    revision = ""
    if crew_state.get("revision_target") == "market_researcher":
        revision = (
            "Reviewer feedback: "
            + crew_state.get("revision_reason", "")
        )

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
            "news_source": news_result.get("source"),
            "news_data_source": news_result.get("data_source"),
            "social": social_result,
            "social_data_source": social_result.get("data_source"),
            "social_sentiment": social_result.get("social_sentiment"),
            "profile": profile,
            "summary": summary,
        },
        "company": company,
        "conversation_log": [
            {"agent": "market_researcher", "message": message}
        ],
    }
