"""Central configuration for InvestPanel.

Every tunable number and every API key lives here, in one place, so no agent or
tool hardcodes a "magic number" inside itself. Values are read from a local
`.env` file (never committed) via python-dotenv. If a key is missing it stays
``None`` here, and the tool that needs it raises a clear error at call time — the
program does not crash on import just because one key is absent.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load key=value lines from a .env file in the project root into the environment.
# Called once, here, so every other module can just read os.getenv results below.
load_dotenv()

# --- Project paths -----------------------------------------------------------
# __file__ is .../src/investpanel/config.py, so two parents up is the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"      # disk cache for every external API call
TRACE_DIR = DATA_DIR / "traces"     # local JSON trace files, one per run

# --- API keys (may be None until the user fills in .env) ---------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# --- LangSmith tracing (entirely optional) -----------------------------------
# A missing LangSmith key must never break a run — we only turn it on if present.
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "investpanel")

# --- LLM settings ------------------------------------------------------------
# Which provider the factory hands out by default. Change LLM_PROVIDER in .env to
# switch every agent at once — no code change needed. Supported values:
#   "gemini" · "openai" · "anthropic" · "groq" · "deepseek" · "openrouter"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_TEMPERATURE = 0.0  # deterministic-ish: we want analysis, not creative writing

# Optional: give the ANALYST a stronger model than the specialists (its cross-check
# is the hard reasoning step). Leave blank to use the same model as everyone else.
# Same provider, just a different model name — e.g. "openai/gpt-oss-120b" on Groq.
ANALYST_MODEL = os.getenv("ANALYST_MODEL") or None

# Each provider needs only its own key when it's the one selected. A default model
# is set per provider but can be overridden in .env.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# DeepSeek uses an OpenAI-compatible API, so we reuse the OpenAI client pointed at
# DeepSeek's base URL. deepseek-chat is the general model; deepseek-reasoner (R1)
# is stronger at reasoning if you want it for the analyst.
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# OpenRouter is a gateway to many models behind one OpenAI-compatible API. It has
# free model variants (e.g. "deepseek/deepseek-r1:free"), so it's a way to run
# DeepSeek R1 at no cost. Model names are namespaced as "vendor/model".
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1:free")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# --- External call behaviour -------------------------------------------------
HTTP_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3               # how many times to retry a failed HTTP call
RETRY_BACKOFF_SECONDS = 2.0   # base wait between retries (grows each attempt)
CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # cache every response for one week

# --- Agent workflow bounds ---------------------------------------------------
# Hard rule: the analyst may loop back to a specialist at most twice. This bound
# lives here so it is impossible to accidentally change it inside the agent code.
MAX_FOLLOWUP_ROUNDS = 2

# --- Financial "healthy range" thresholds ------------------------------------
# Rough rules of thumb, kept here (not inside the agent) so they're easy to see
# and adjust. These decide the yes/no "healthy" flag on each FinancialFinding.
# They are heuristics for a learning project, not precise investing rules.
HEALTHY_DEBT_TO_EQUITY_MAX = 1.0     # below ~1.0x is generally comfortable
HEALTHY_INTEREST_COVERAGE_MIN = 3.0  # EBIT covers interest at least ~3x
HEALTHY_ROCE_MIN = 0.10              # 10%+ return on capital employed
HEALTHY_ROE_MIN = 0.12              # 12%+ return on equity
HEALTHY_PE_MAX = 25.0               # above this looks expensive on earnings
HEALTHY_PB_MAX = 5.0               # above this looks expensive on book value
HEALTHY_PEG_MAX = 1.5              # valuation reasonable vs growth (PEG-like)

# --- Risk thresholds ---------------------------------------------------------
# Annualized volatility above this is flagged as "elevated" by the Risk agent.
HIGH_VOLATILITY_THRESHOLD = 0.40
