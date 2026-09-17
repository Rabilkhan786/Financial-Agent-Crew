"""Small helper for calling the Groq language model."""

from langchain_groq import ChatGroq

from src.components import config
from src.components.logging import get_logger

log = get_logger(__name__)
_model = None


def get_llm():
    """Create the model once and reuse it."""
    global _model

    if _model is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set in .env")

        _model = ChatGroq(
            model=config.GROQ_MODEL,
            api_key=config.GROQ_API_KEY,
            temperature=config.LLM_TEMPERATURE,
            timeout=config.REQUEST_TIMEOUT,
            max_tokens=config.MAX_OUTPUT_TOKENS,
        )

    return _model


def ask(prompt):
    """Send one prompt and return plain text."""
    try:
        response = get_llm().invoke(prompt)
        return str(response.content).strip()
    except Exception as error:
        log.error("LLM call failed: %s", error)
        return ""
