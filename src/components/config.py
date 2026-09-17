"""Load project settings from config.yaml and secrets from .env."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

load_dotenv(PROJECT_ROOT / ".env")

with CONFIG_PATH.open("r", encoding="utf-8") as file:
    SETTINGS = yaml.safe_load(file) or {}

LLM = SETTINGS.get("llm", {})
ANALYSIS = SETTINGS.get("analysis", {})
WORKFLOW = SETTINGS.get("workflow", {})
PATHS = SETTINGS.get("paths", {})
LOGGING = SETTINGS.get("logging", {})

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = LLM.get("model", "openai/gpt-oss-120b")
LLM_TEMPERATURE = float(LLM.get("temperature", 0.2))
REQUEST_TIMEOUT = float(LLM.get("timeout", 180))
MAX_OUTPUT_TOKENS = int(LLM.get("max_tokens", 4096))

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", API_URL).rstrip("/")

RISK_FREE_RATE = float(ANALYSIS.get("risk_free_rate", 0.0))
STATEMENT_YEARS = int(ANALYSIS.get("statement_years", 5))
NEWS_LIMIT = int(ANALYSIS.get("news_limit", 10))
SOCIAL_LIMIT = int(ANALYSIS.get("social_limit", 30))
MIN_SOCIAL_POSTS = int(ANALYSIS.get("min_social_posts", 5))

MAX_REVISIONS = int(WORKFLOW.get("max_revisions", 1))
RECURSION_LIMIT = int(WORKFLOW.get("recursion_limit", 20))

OUTPUT_DIR = PROJECT_ROOT / PATHS.get("output", "output")
LOG_LEVEL = str(LOGGING.get("level", "INFO")).upper()


def missing_required():
    """Return required environment variables that are missing."""
    return [] if GROQ_API_KEY else ["GROQ_API_KEY"]


def enabled_sources():
    """Return the main services used by the project."""
    return {
        f"Groq ({GROQ_MODEL})": bool(GROQ_API_KEY),
        "Yahoo Finance": True,
        "StockTwits": True,
    }
