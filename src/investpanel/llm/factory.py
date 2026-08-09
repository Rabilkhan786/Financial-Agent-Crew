"""LLM factory — one function that hands back a chat model.

Every agent asks this factory for its model instead of constructing one itself.
That means switching provider or model is a one-line change here, and the rest of
the code never needs to know which LLM is behind it. Gemini is the default. To
run an ablation (e.g. give the Analyst a different provider than the specialists),
call get_llm with a different ``provider`` argument.
"""

from investpanel import config


def get_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
):
    """Return a LangChain chat model for the requested provider.

    Defaults come from config. We check for the required key here and raise a
    clear message, rather than letting the underlying library fail with a vague
    error deep inside a request.
    """
    provider = provider or config.LLM_PROVIDER
    temperature = config.LLM_TEMPERATURE if temperature is None else temperature

    if provider == "gemini":
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
        # Imported inside the branch so adding another provider later never forces
        # this one's package to be installed.
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model or config.GEMINI_MODEL,
            google_api_key=config.GEMINI_API_KEY,
            temperature=temperature,
        )

    raise ValueError(
        f"Unknown LLM provider '{provider}'. Add a branch for it in llm/factory.py."
    )
