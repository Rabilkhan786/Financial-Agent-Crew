"""The one place that talks to Gemini.

Every agent calls `ask()` or `ask_json()` from here. Keeping the model in one
file means the model name, the temperature and the JSON parsing are set once
instead of being copied into five agents.
"""

from __future__ import annotations

import json

from langchain_google_genai import ChatGoogleGenerativeAI

from src import config

log = config.get_logger(__name__)

_model = None


def get_llm() -> ChatGoogleGenerativeAI:
    """The Gemini model, made once and reused."""
    global _model
    if _model is None:
        if not config.GOOGLE_API_KEY:
            raise RuntimeError("GOOGLE_API_KEY is not set in .env")
        _model = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=config.LLM_TEMPERATURE,
        )
        log.info("using model %s", config.GEMINI_MODEL)
    return _model


def text_of(reply) -> str:
    """Get plain text out of a model reply.

    Gemini 3 returns `content` as a list of blocks rather than a string, so
    calling .strip() on it directly raises. This flattens both shapes.
    """
    content = reply.content
    if isinstance(content, str):
        return content.strip()

    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts).strip()


def ask(prompt: str) -> str:
    """Send a prompt, get text back. Returns "" if the call fails."""
    try:
        return text_of(get_llm().invoke(prompt))
    except Exception as error:
        log.error("model call failed: %s", error)
        return ""


def _strip_code_fence(text: str) -> str:
    """Remove the ```json ... ``` wrapper models often add."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]          # drop the opening fence line
        text = text.rsplit("```", 1)[0]         # drop the closing fence
    return text.strip()


def ask_json(prompt: str, retries: int = 1) -> dict:
    """Send a prompt that should return JSON, and parse it.

    Models sometimes wrap JSON in a code fence or add a sentence before it, so
    one retry is allowed with a blunter instruction. An empty dict is returned
    if it still is not valid JSON — the caller decides what to do about that,
    because a failed parse must not stop the whole run.
    """
    for attempt in range(retries + 1):
        reply = ask(prompt if attempt == 0
                    else prompt + "\n\nReturn only valid JSON. No other text.")
        if not reply:
            continue
        try:
            parsed = json.loads(_strip_code_fence(reply))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            log.warning("reply was not valid JSON (attempt %d)", attempt + 1)
    return {}
