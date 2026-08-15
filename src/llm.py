"""The one place that talks to Gemini.

Every agent calls `ask()` or `ask_json()` from here. Keeping the model in one
file means the model name, the temperature and the JSON parsing are set once
instead of being copied into five agents.
"""

import json
import re
import time

from langchain_google_genai import ChatGoogleGenerativeAI

from src import config

log = config.get_logger(__name__)

_model = None


def get_llm():
    """The model, made once and reused. Gemini or Groq, set in .env."""
    global _model
    if _model is not None:
        return _model

    if config.LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama

        # reasoning=False turns off qwen3-style thinking. Left on, the model
        # leaks "/think" and <think> blocks into the answer, which would end up
        # printed in the report.
        _model = ChatOllama(
            model=config.OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=config.LLM_TEMPERATURE,
            reasoning=False,
        )
        log.info("using local Ollama model %s", config.OLLAMA_MODEL)
    elif config.LLM_PROVIDER == "groq":
        from langchain_groq import ChatGroq

        if not config.GROQ_API_KEY:
            raise RuntimeError("LLM_PROVIDER is groq but GROQ_API_KEY is not set in .env")
        _model = ChatGroq(
            model=config.GROQ_MODEL,
            api_key=config.GROQ_API_KEY,
            temperature=config.LLM_TEMPERATURE,
        )
        log.info("using Groq model %s", config.GROQ_MODEL)
    else:
        if not config.GOOGLE_API_KEY:
            raise RuntimeError("GOOGLE_API_KEY is not set in .env")
        _model = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=config.LLM_TEMPERATURE,
        )
        log.info("using Gemini model %s", config.GEMINI_MODEL)
    return _model


def text_of(reply):
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


def wait_for(error, attempt):
    """How long to wait before trying again.

    A rate-limited provider says how long it needs - "try again in 8.7s" - so
    use that rather than guessing. Guessing too short wasted the retry and left
    the report as a stub.
    """
    match = re.search(r"try again in ([0-9.]+)(ms|s)", str(error))
    if match:
        seconds = float(match.group(1))
        if match.group(2) == "ms":
            seconds = seconds / 1000
        return min(seconds + 1, 60)
    return 5 * (attempt + 1)


def ask(prompt, attempts=4):
    """Send a prompt, get text back. Returns "" if it keeps failing.

    Free plans limit tokens per minute, and running several companies in a row
    hits that. The limit clears in seconds, so waiting and trying again turns a
    lost report into a slightly slower one. Without this a single 429 left the
    report as a stub.
    """
    for attempt in range(attempts):
        try:
            return text_of(get_llm().invoke(prompt))
        except Exception as error:
            last = error
            if attempt < attempts - 1:
                pause = wait_for(error, attempt)
                log.warning("model call failed (%s), waiting %.1fs and trying again",
                            str(error)[:90], pause)
                time.sleep(pause)
    log.error("model call failed after %d attempts: %s", attempts, last)
    return ""


def _strip_code_fence(text):
    """Remove the ```json ... ``` wrapper models often add."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]          # drop the opening fence line
        text = text.rsplit("```", 1)[0]         # drop the closing fence
    return text.strip()


def ask_json(prompt, retries=1):
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
