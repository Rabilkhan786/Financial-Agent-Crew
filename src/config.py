"""One place for every setting and every key.

`.env` is read once, here, at startup. Nothing else in the project calls
`os.getenv`, so there is a single file to look at when asking "what does this
need to run?" or "why is that feature switched off?".

Only GROQ_API_KEY is required. Every other key is optional and switches on an
extra capability; the app runs without all of them.
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get(name, default=""):
    """An environment value with whitespace and stray quotes stripped off."""
    return os.getenv(name, default).strip().strip('"').strip("'")


# --- The model --------------------------------------------------------------
GROQ_API_KEY = _get("GROQ_API_KEY")
GROQ_MODEL = _get("GROQ_MODEL", "openai/gpt-oss-120b")
LLM_TEMPERATURE = float(_get("LLM_TEMPERATURE", "0.2") or 0.2)

# The free tier allows a few thousand tokens a minute, and one report uses a
# lot of them. Pacing the calls keeps a ten-company run under the limit; the
# retry in llm.py is only the backstop.
CALLS_PER_SECOND = float(_get("CALLS_PER_SECOND", "0.12") or 0.12)

# How long to let one model call run. A reasoning model thinks before it
# writes, and the report prompt is the longest one here, so the default was
# too short and those calls were cut off mid-answer.
REQUEST_TIMEOUT = float(_get("REQUEST_TIMEOUT", "180") or 180)

# How much the model may write in one answer. A reasoning model spends part of
# this budget thinking before it writes anything, and the default was small
# enough that the whole budget went on thought: the reply came back empty and
# the report was printed with no sections at all. Big enough for both now.
MAX_OUTPUT_TOKENS = int(_get("MAX_OUTPUT_TOKENS", "4096") or 4096)

# --- Optional: extra data sources -------------------------------------------
REDDIT_CLIENT_ID = _get("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = _get("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = _get("REDDIT_USER_AGENT", "financial-analysis-crew/0.1")
FINNHUB_API_KEY = _get("FINNHUB_API_KEY")
ALPHAVANTAGE_API_KEY = _get("ALPHAVANTAGE_API_KEY")

# What is switched on. Read these rather than testing the keys by hand, so the
# rule for "is this available?" lives in one place.
HAS_GROQ = bool(GROQ_API_KEY)
HAS_REDDIT = bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET)
HAS_FINNHUB = bool(FINNHUB_API_KEY)
HAS_ALPHAVANTAGE = bool(ALPHAVANTAGE_API_KEY)

# --- Folders ----------------------------------------------------------------
CACHE_DIR = Path(_get("CACHE_DIR", ".cache"))
OUTPUT_DIR = Path(_get("OUTPUT_DIR", "output"))

# --- Tunables ---------------------------------------------------------------
# The revise loop is capped so a disagreement between agents cannot spin
# forever; LangGraph's own recursion limit is the backstop behind that.
MAX_REVISIONS = int(_get("MAX_REVISIONS", "2") or 2)
RECURSION_LIMIT = int(_get("RECURSION_LIMIT", "25") or 25)

# Sharpe needs a risk-free rate. It differs by market and by year, so it is a
# setting rather than a number buried in the maths, and the report states which
# rate was used.
RISK_FREE_RATE = float(_get("RISK_FREE_RATE", "0.0") or 0.0)

# How long each kind of fetched data stays usable before it is fetched again.
CACHE_HOURS_STATEMENTS = 24.0     # updated four times a year at most
CACHE_HOURS_PRICES = 12.0
CACHE_HOURS_NEWS = 6.0
CACHE_HOURS_SOCIAL = 6.0

# Data volumes
STATEMENT_YEARS = 5
NEWS_LIMIT = 10
NEWS_DAYS = 30
SOCIAL_LIMIT = 50
MIN_SOCIAL_POSTS = 5              # below this, the answer is "insufficient data"


def missing_required():
    """Which required settings are absent. Empty list means ready to run.

    Only the key for the provider actually in use is required.
    """
    return [] if GROQ_API_KEY else ["GROQ_API_KEY"]


def enabled_sources():
    """What each optional key switches on — shown in the app so the user can
    see at a glance why a section of the report is thin."""
    return {
        f"Groq ({GROQ_MODEL})": HAS_GROQ,
        "Yahoo Finance (no key needed)": True,
        "Reddit posts": HAS_REDDIT,
        "StockTwits posts (no key needed)": not HAS_REDDIT,
        "Finnhub news": HAS_FINNHUB,
        "Alpha Vantage news sentiment": HAS_ALPHAVANTAGE,
    }


# --- Logging ----------------------------------------------------------------
# Every fetch, cache hit and agent step is logged. During a multi-agent run the
# log is often the only way to see which agent asked for what, and in which
# order, without attaching a debugger.
LOG_LEVEL = _get("LOG_LEVEL", "INFO").upper()
LOG_FILE = OUTPUT_DIR / "run.log"

_LOG_FORMAT = "%(asctime)s  %(levelname)-7s %(name)-22s %(message)s"
_logging_ready = False


def setup_logging(level=None):
    """Send logs to the console and to output/run.log. Safe to call repeatedly.

    Streamlit re-imports modules on every interaction, so this guards against
    stacking up duplicate handlers and printing each line several times.
    """
    global _logging_ready
    root = logging.getLogger("crew")
    if _logging_ready:
        return root

    root.setLevel(level or LOG_LEVEL)
    root.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%H:%M:%S"))
    root.addHandler(console)

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        to_file = logging.FileHandler(LOG_FILE, encoding="utf-8")
        to_file.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(to_file)
    except OSError:
        pass      # a read-only disk must not stop the run

    _logging_ready = True
    return root


def get_logger(name):
    """The logger a module should use: `log = config.get_logger(__name__)`."""
    setup_logging()
    return logging.getLogger(f"crew.{name.replace('src.', '')}")
