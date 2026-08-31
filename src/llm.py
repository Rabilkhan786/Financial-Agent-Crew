"""This file talks to the Groq model. Nothing else in the project calls the
model directly.
"""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_groq import ChatGroq

from src import config

log = config.get_logger(__name__)

_base = None

RETRY = {"stop_after_attempt": 5, "wait_exponential_jitter": True}


def get_base():
    """The model, made once and reused.

    The free tier allows a few thousand tokens a minute. Waiting for a 429 and
    retrying was not enough - running ten companies in a row still lost reports
    to it. Pacing the calls up front, and keeping the retry as a backstop, is
    the more reliable order.
    """
    global _base
    if _base is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        pace = InMemoryRateLimiter(
            requests_per_second=config.CALLS_PER_SECOND,
            check_every_n_seconds=0.5,
            max_bucket_size=2,
        )
        _base = ChatGroq(
            model=config.GROQ_MODEL,
            api_key=config.GROQ_API_KEY,
            temperature=config.LLM_TEMPERATURE,
            rate_limiter=pace,
            # Without this, reasoning models put their whole train of thought
            # in the answer instead of just the report.
            reasoning_format="hidden",
            # The report prompt is the longest one here, and the default
            # timeout was cutting those calls off mid-answer.
            timeout=config.REQUEST_TIMEOUT,
            max_tokens=config.MAX_OUTPUT_TOKENS,
        )
        log.info("using %s, paced at %s calls/second",
                 config.GROQ_MODEL, config.CALLS_PER_SECOND)
    return _base


def get_llm():
    """The model with retries, for plain text answers."""
    return get_base().with_retry(**RETRY)


def ask(prompt):
    """Send a prompt, get text back. Returns "" if the model cannot be reached."""
    try:
        return (get_llm() | StrOutputParser()).invoke(prompt).strip()
    except Exception as error:
        log.error("model call failed: %s", str(error)[:200])
        return ""


def ask_structured(prompt, schema):
    """Send a prompt and get back a filled-in schema object, or None.

    LangChain asks the model to answer in the shape of the schema and parses
    the reply itself, so there is no JSON handling to write or to get wrong.
    """
    try:
        # Order matters here. Calling .with_structured_output() on an
        # already-retrying model raises, since the retry wrapper doesn't
        # carry that method through.
        model = get_base().with_structured_output(schema)
        model = model.with_retry(**RETRY)
        return model.invoke(prompt)
    except Exception as error:
        log.error("structured call failed: %s", str(error)[:200])
        return None
