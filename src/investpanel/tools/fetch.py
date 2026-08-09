"""Article fetcher — turn a URL into clean readable text.

The News agent must summarize real articles in its own words, so it needs the
actual body text of a page, not just a search snippet. We download the raw HTML
(cached, like every other external call) and use trafilatura to strip away menus,
ads, and boilerplate, leaving the main article text. Enforcing "summary comes
from a really-fetched page" is how we keep the no-unsourced-facts rule honest.
"""

import trafilatura

from investpanel.tools import cache


def fetch_article_text(url: str) -> str:
    """Download a page and return its main text, or raise if nothing usable.

    We cache the raw HTML so re-runs don't re-download. trafilatura.extract does
    the readability work; if it can't find real article text (paywall, JS-only
    page) we raise, because a NewsFinding with no real text behind it is exactly
    what the no-unsourced-facts rule forbids.
    """
    html = cache.cached_get_text(url, cache_key=f"fetch:html:{url}")
    text = trafilatura.extract(html)
    if not text:
        raise ValueError(f"Could not extract article text from {url}")
    return text
