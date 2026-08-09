"""Tracing — always save a local JSON record, optionally send to LangSmith.

A "trace" is just a saved record of what happened during a run: what went in,
what came out, and some metadata. We always write one JSON file per event to
``data/traces/`` so there is a permanent, inspectable history on disk. If the
user has a LangSmith key we also turn on LangSmith's automatic LangChain tracing
for nicer dashboards — but a missing LangSmith key must never break a run, so
turning it on is wrapped so it can only ever help, never fail the program.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from investpanel import config
from investpanel.utils.logging import get_logger

logger = get_logger(__name__)

# So init_langsmith can be called from every entry point but only acts once.
_langsmith_ready = False


def init_langsmith() -> bool:
    """Turn on LangSmith tracing if a key is present. Returns True if enabled.

    LangChain/LangGraph read these environment variables automatically, so all we
    have to do is set them. If there is no key we do nothing and return False —
    the run continues exactly the same, just without the LangSmith dashboard.
    Safe to call repeatedly: it only sets things up once.
    """
    global _langsmith_ready
    if _langsmith_ready:
        return True
    if not config.LANGSMITH_API_KEY:
        logger.info("LangSmith key not set — using local JSON traces only.")
        return False
    import os

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = config.LANGSMITH_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = config.LANGSMITH_PROJECT
    _langsmith_ready = True
    logger.info("LangSmith tracing enabled for project '%s'.", config.LANGSMITH_PROJECT)
    return True


def save_trace(name: str, data: dict[str, Any]) -> Path:
    """Write one trace record to data/traces/ and return the file path.

    The filename starts with a UTC timestamp so files sort in run order. We add
    the timestamp into the record too, so the file is self-describing if moved.
    """
    config.TRACE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%f")
    record = {"name": name, "timestamp_utc": timestamp, **data}
    path = config.TRACE_DIR / f"{timestamp}_{name}.json"
    # default=str so anything not JSON-native (dates, enums) still serializes.
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote trace: %s", path.name)
    return path
