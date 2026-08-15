"""Gathers what is being said about the company, and summarises it.

News headlines and retail posts only. This agent never touches the financial
statements - that is the fundamentals analyst's job, and keeping them separate
is what lets the orchestrator later notice when the two disagree.
"""

from src import config, llm, state
from src.tools import market_data, news, social, sourcing

log = config.get_logger(__name__)

PROMPT = """You are a market researcher briefing a private investor.

Company: {company} ({ticker})
Sector: {sector}

Recent news headlines (these are real articles, with their dates):
{headlines}

Retail investor chatter: {social_sentiment}

News sentiment score: {news_sentiment}

{revision}

Write 2 short paragraphs in plain English:
1. What has actually happened at or around this company recently?
2. What is the mood - and how much weight does it deserve?

Rules:
- Only use the headlines listed above. Do not add events you remember.
- Every number you write must appear in the headlines above. If a headline says
  profit rose 34%, write 34%. Do not widen it to "34-45%", do not round it, and
  do not add a figure of your own such as a price target or a deal size.
- If the chatter says "insufficient data", say so plainly and move on. Do not
  guess at a mood from nothing.
- Do not predict the share price.
"""


def _headline_text(articles):
    if not articles:
        return "- no recent articles found"
    lines = []
    for article in articles:
        summary = article.get("summary") or ""
        lines.append(f"- [{article.get('published', 'undated')}] {article['title']}"
                     + (f" - {summary[:200]}" if summary else ""))
    return "\n".join(lines)


def run(crew_state):
    """Fetch news and social posts, then summarise the mood."""
    ticker = crew_state["ticker"]
    log.info("market_researcher: starting %s", ticker)

    profile = market_data.fetch_profile(ticker)
    company = crew_state.get("company") or profile.get("name") or ticker

    headlines = news.fetch_news(ticker)
    chatter = social.fetch_social_posts(ticker, company)

    sentiment = headlines.get("sentiment") or {}
    if sentiment.get("average_score") is not None:
        news_sentiment = (f"{sentiment['label']} "
                          f"(score {sentiment['average_score']:+.2f} "
                          f"across {sentiment['articles_scored']} articles)")
    else:
        news_sentiment = "not scored - no sentiment provider configured"

    revision = ""
    if crew_state.get("revision_target") == "market_researcher":
        revision = ("The reviewer sent this back with a specific request. "
                    f"Address it directly: {crew_state.get('revision_reason', '')}")

    summary_text = llm.ask(PROMPT.format(
        company=company,
        ticker=ticker,
        sector=profile.get("sector") or "unknown",
        headlines=_headline_text(headlines["articles"]),
        social_sentiment=chatter["social_sentiment"],
        news_sentiment=news_sentiment,
        revision=revision,
    ))

    # Check the researcher against its own sources before the summary travels on.
    # The report writer treats this text as supplied fact, so a number invented
    # here becomes a number in the final report.
    sources = {"research": {"articles": headlines["articles"], "social": chatter}}
    invented = sourcing.unsourced_numbers(sources, summary_text)
    if invented:
        log.warning("market_researcher: %s not in any headline - asking again", invented)
        summary_text = llm.ask(
            PROMPT.format(
                company=company, ticker=ticker,
                sector=profile.get("sector") or "unknown",
                headlines=_headline_text(headlines["articles"]),
                social_sentiment=chatter["social_sentiment"],
                news_sentiment=news_sentiment,
                revision=(f"Your last answer used these numbers, which appear in no "
                          f"headline: {', '.join(invented)}. Write it again without "
                          "them. Use only figures printed in the headlines above."))
        ) or summary_text

    summary = (f"Found {headlines['article_count']} articles via {headlines['source']} "
               f"and {chatter['post_count']} posts via {chatter['source']}.")
    log.info("market_researcher: %s", summary)

    return {
        "research": {
            "articles": headlines["articles"],
            "news_source": headlines["source"],
            "news_sentiment": sentiment or None,
            "social": chatter,
            "social_sentiment": chatter["social_sentiment"],
            "profile": profile,
            "summary": summary_text,
        },
        "company": company,
        "conversation_log": [state.note("market_researcher", summary)],
    }
