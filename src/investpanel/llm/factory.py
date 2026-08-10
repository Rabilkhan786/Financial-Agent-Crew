"""LLM factory — one function that hands back a chat model.

Every agent asks this factory for its model instead of building one itself, so
switching provider is a single change (set ``LLM_PROVIDER`` in .env) that applies
to the whole system at once. Providers wired up: "gemini" (Google), "openai"
(ChatGPT), "anthropic" (Claude), "groq", "deepseek", and "openrouter" (a gateway
with free model variants like DeepSeek R1). You pick whichever you like; adding
another is one more small branch below. (DeepSeek and OpenRouter are both
OpenAI-compatible, so they reuse the OpenAI client with a different base URL — no
extra library.)

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
            max_retries=config.LLM_MAX_RETRIES,
        )

    if provider == "openai":
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or config.OPENAI_MODEL,
            api_key=config.OPENAI_API_KEY,
            temperature=temperature,
            max_retries=config.LLM_MAX_RETRIES,
        )

    if provider == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model or config.ANTHROPIC_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=temperature,
            max_retries=config.LLM_MAX_RETRIES,
        )

    if provider == "groq":
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=model or config.GROQ_MODEL,
            api_key=config.GROQ_API_KEY,
            temperature=temperature,
            max_retries=config.LLM_MAX_RETRIES,
        )

    if provider == "deepseek":
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY is not set. Add it to your .env file.")
        # DeepSeek is OpenAI-compatible: same client, different base_url.
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or config.DEEPSEEK_MODEL,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            temperature=temperature,
            max_retries=config.LLM_MAX_RETRIES,
        )

    if provider == "openrouter":
        if not config.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not set. Add it to your .env file.")
        # OpenRouter is OpenAI-compatible too: same client, OpenRouter's base_url.
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or config.OPENROUTER_MODEL,
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
            temperature=temperature,
            max_retries=config.LLM_MAX_RETRIES,
        )

    raise ValueError(
        f"Unknown LLM provider '{provider}'. Supported: 'gemini', 'openai', "
        "'anthropic', 'groq', 'deepseek', 'openrouter'. "
        "Add a branch for a new one in llm/factory.py."
    )
