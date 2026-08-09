"""The shared machinery every agent inherits.

Per the project conventions, the boring-but-important plumbing lives here once so
each agent stays small and focused: getting an LLM, asking it for JSON and
retrying if the reply isn't valid JSON, and writing a trace of what happened.
Agents subclass this and add only their own logic. Deliberately shallow — there
is exactly one base class, no tower of intermediate ones.
"""

import json

from investpanel.llm.factory import get_llm
from investpanel.utils.logging import get_logger
from investpanel.utils.tracing import save_trace

logger = get_logger(__name__)


class BaseAgent:
    """Base for all agents: holds the LLM and provides JSON + trace helpers."""

    name: str = "agent"

    def __init__(self, llm=None):
        # Agents that don't call the LLM (e.g. the deterministic Risk agent) still
        # accept one for a consistent constructor, but simply never use it.
        self.llm = llm

    def _ensure_llm(self):
        """Create the default LLM the first time an agent actually needs it."""
        if self.llm is None:
            self.llm = get_llm()
        return self.llm

    def invoke_json(self, prompt: str, retries: int = 2):
        """Ask the LLM for JSON and parse it, retrying once if the reply is bad.

        Models sometimes return prose or a half-formed object. Rather than crash,
        we re-ask up to ``retries`` times with a firm reminder to return JSON only.
        If it still fails we raise a clear error naming the agent.
        """
        llm = self._ensure_llm()
        last_error: Exception | None = None
        message = prompt
        for _ in range(retries):
            reply = llm.invoke(message)
            text = getattr(reply, "content", str(reply))
            try:
                return self._parse_json(text)
            except (json.JSONDecodeError, ValueError) as error:
                last_error = error
                message = (
                    prompt
                    + "\n\nYour previous reply was not valid JSON. "
                    "Reply with ONLY a valid JSON value and nothing else."
                )
        raise ValueError(
            f"{self.name}: model did not return valid JSON after {retries} attempts"
        ) from last_error

    @staticmethod
    def _parse_json(text: str):
        """Parse JSON, tolerating ```json ... ``` code fences around it."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.removeprefix("json").strip()
        return json.loads(cleaned)

    def trace(self, event: dict) -> None:
        """Write a local JSON trace tagged with this agent's name."""
        save_trace(self.name, event)
