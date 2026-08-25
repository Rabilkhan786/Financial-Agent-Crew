"""The one place that talks to the model.

Groq, through LangChain. Everything that used to be hand-written here is now
done by the framework:

* `.with_retry()` handles rate limits, instead of our own loop and sleep.
* `StrOutputParser()` pulls the text out of the reply.
* `.with_structured_output()` fills in a schema, instead of parsing JSON and
  stripping code fences by hand.
"""

from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

from src import config

log = config.get_logger(__name__)

_model = None


def get_llm():
    """The model, made once and reused.

    with_retry covers the tokens-per-minute limit on the free tier: running
    several companies in a row hits it, and the limit clears in seconds.
    """
    global _model
    if _model is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        _model = ChatGroq(
            model=config.GROQ_MODEL,
            api_key=config.GROQ_API_KEY,
            temperature=config.LLM_TEMPERATURE,
        ).with_retry(stop_after_attempt=5, wait_exponential_jitter=True)
        log.info("using %s", config.GROQ_MODEL)
    return _model


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
        return get_llm().with_structured_output(schema).invoke(prompt)
    except Exception as error:
        log.error("structured call failed: %s", str(error)[:200])
        return None
