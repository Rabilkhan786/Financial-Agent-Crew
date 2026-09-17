"""Read project settings and configure logging."""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get(name, default=""):
    """Return a trimmed environment value."""
    return os.getenv(name, default).strip().strip('"').strip("'")


GROQ_API_KEY = _get("GROQ_API_KEY")
GROQ_MODEL = _get("GROQ_MODEL", "openai/gpt-oss-120b")
LLM_TEMPERATURE = float(_get("LLM_TEMPERATURE", "0.2") or 0.2)
CALLS_PER_SECOND = float(_get("CALLS_PER_SECOND", "0.12") or 0.12)
REQUEST_TIMEOUT = float(_get("REQUEST_TIMEOUT", "180") or 180)
MAX_OUTPUT_TOKENS = int(_get("MAX_OUTPUT_TOKENS", "4096") or 4096)

API_URL = _get("API_URL", "http://localhost:8000")
# In Docker, API_URL can be an internal service name while chart images are
# loaded by the user's browser. API_PUBLIC_URL is the browser-facing address.
API_PUBLIC_URL = _get("API_PUBLIC_URL", "") or API_URL

FINNHUB_API_KEY = _get("FINNHUB_API_KEY")
ALPHAVANTAGE_API_KEY = _get("ALPHAVANTAGE_API_KEY")

HAS_GROQ = bool(GROQ_API_KEY)
HAS_FINNHUB = bool(FINNHUB_API_KEY)
HAS_ALPHAVANTAGE = bool(ALPHAVANTAGE_API_KEY)

CACHE_DIR = Path(_get("CACHE_DIR", ".cache"))
OUTPUT_DIR = Path(_get("OUTPUT_DIR", "output"))

MAX_REVISIONS = int(_get("MAX_REVISIONS", "2") or 2)
RECURSION_LIMIT = int(_get("RECURSION_LIMIT", "25") or 25)
RISK_FREE_RATE = float(_get("RISK_FREE_RATE", "0.0") or 0.0)

CACHE_HOURS_STATEMENTS = 24.0
CACHE_HOURS_PRICES = 12.0
CACHE_HOURS_NEWS = 6.0
CACHE_HOURS_SOCIAL = 6.0

STATEMENT_YEARS = 5
NEWS_LIMIT = 10
NEWS_DAYS = 30
SOCIAL_LIMIT = 50
MIN_SOCIAL_POSTS = 5


def missing_required():
    """Return required settings that are not configured."""
    return [] if GROQ_API_KEY else ["GROQ_API_KEY"]


def enabled_sources():
    """Return the data/model sources currently available to the app."""
    return {
        f"Groq ({GROQ_MODEL})": HAS_GROQ,
        "Yahoo Finance (no key needed)": True,
        "StockTwits posts (no key needed)": True,
        "Finnhub news": HAS_FINNHUB,
        "Alpha Vantage news sentiment": HAS_ALPHAVANTAGE,
    }


LOG_LEVEL = _get("LOG_LEVEL", "INFO").upper()
LOG_FILE = OUTPUT_DIR / "run.log"
_LOG_FORMAT = "%(asctime)s  %(levelname)-7s %(name)-22s %(message)s"
_logging_ready = False


def setup_logging(level=None):
    """Configure console and file logging once."""
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
    except OSError as error:
        # File logging is optional, but the console should explain why it is
        # unavailable instead of silently hiding the problem.
        root.warning("file logging disabled: %s", error)

    _logging_ready = True
    return root


def get_logger(name):
    """Return a project logger for one module."""
    setup_logging()
    return logging.getLogger(f"crew.{name.replace('src.', '')}")
