"""LLM factory — one function that hands back a chat model.

Every agent asks this factory for its model instead of building one itself, so
switching provider is a single change (set ``LLM_PROVIDER`` in .env) that applies
to the whole system at once. Four providers are wired up: "gemini" (Google),
"openai" (ChatGPT), "anthropic" (Claude), and "groq". You pick whichever you like;
adding another is just one more small branch below — that is the whole point of
keeping this in one place.

To run the Phase 5 ablation — giving the Analyst a different provider than the
specialists — call e.g. ``get_llm(provider="anthropic")`` for that one agent.
"""

from investpanel import config


def get_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
):
    """Return a LangChain chat model for the requested provider.

    Defaults come from config (``LLM_PROVIDER`` etc.). We check for the required
    key here and raise a clear message, rather than letting the underlying library
    fail with a vague error deep inside a request.
    """
    provider = (provider or config.LLM_PROVIDER).lower()
    temperature = config.LLM_TEMPERATURE if temperature is None else temperature

    if provider == "gemini":
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
        # Imported inside the branch so a provider you don't use never needs to be
        # installed or configured.
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model or config.GEMINI_MODEL,
            google_api_key=config.GEMINI_API_KEY,
            temperature=temperature,
        )

    if provider == "openai":
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or config.OPENAI_MODEL,
            api_key=config.OPENAI_API_KEY,
            temperature=temperature,
        )

    if provider == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model or config.ANTHROPIC_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=temperature,
        )

    if provider == "groq":
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=model or config.GROQ_MODEL,
            api_key=config.GROQ_API_KEY,
            temperature=temperature,
        )

    raise ValueError(
        f"Unknown LLM provider '{provider}'. "
        "Supported: 'gemini', 'openai', 'anthropic', 'groq'. "
        "Add a branch for a new one in llm/factory.py."
    )
