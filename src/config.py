"""Reads all settings from the .env file.

Only GROQ_API_KEY is required, everything else is optional.
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

# Free tier limit is a few thousand tokens a minute. Pacing calls keeps a
# ten-company run under it; the retry in llm.py is just the backstop.
CALLS_PER_SECOND = float(_get("CALLS_PER_SECOND", "0.12") or 0.12)

# Reasoning models think before they write, so the report prompt needs a
# longer timeout than the default.
REQUEST_TIMEOUT = float(_get("REQUEST_TIMEOUT", "180") or 180)

# Also higher than default: a reasoning model spends part of this budget
# thinking, so a small limit left no room for the actual report.
MAX_OUTPUT_TOKENS = int(_get("MAX_OUTPUT_TOKENS", "4096") or 4096)

# --- Where the Streamlit app finds the API ----------------------------------
# The app has no model calls or data fetches of its own - it asks the API
# for everything.
API_URL = _get("API_URL", "http://localhost:8000")

# API_URL is used server-side (inside Docker Compose that's http://api:8000,
# only reachable between containers). Chart images are the one exception:
# the browser loads them directly, and it can't resolve "api" as a host.
# API_PUBLIC_URL is that browser-facing address. Defaults to API_URL, which
# is correct anywhere both halves share one "localhost". docker-compose.yml
# is the one place that sets it differently.
API_PUBLIC_URL = _get("API_PUBLIC_URL", "") or API_URL

# --- Optional: extra data sources -------------------------------------------
FINNHUB_API_KEY = _get("FINNHUB_API_KEY")
ALPHAVANTAGE_API_KEY = _get("ALPHAVANTAGE_API_KEY")

# What is switched on. Read these rather than testing the keys by hand, so the
# rule for "is this available?" lives in one place.
HAS_GROQ = bool(GROQ_API_KEY)
HAS_FINNHUB = bool(FINNHUB_API_KEY)
HAS_ALPHAVANTAGE = bool(ALPHAVANTAGE_API_KEY)

# --- Folders ----------------------------------------------------------------
CACHE_DIR = Path(_get("CACHE_DIR", ".cache"))
OUTPUT_DIR = Path(_get("OUTPUT_DIR", "output"))

# --- Tunables ---------------------------------------------------------------
# Caps the revise loop so agents can't disagree forever. LangGraph's own
# recursion limit is the backstop behind that.
MAX_REVISIONS = int(_get("MAX_REVISIONS", "2") or 2)
RECURSION_LIMIT = int(_get("RECURSION_LIMIT", "25") or 25)

# Sharpe needs a risk-free rate, and it differs by market and year, so it's a
# setting, not a number buried in the maths.
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
        "StockTwits posts (no key needed)": True,
        "Finnhub news": HAS_FINNHUB,
        "Alpha Vantage news sentiment": HAS_ALPHAVANTAGE,
    }


# --- Logging ----------------------------------------------------------------
# Every fetch, cache hit and agent step is logged - the log is the easiest
# way to see who asked for what, in what order, during a run.
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
