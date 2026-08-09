"""A tiny, shared logger setup.

One helper so every module logs in the same format instead of using bare
``print`` calls. Nothing clever here on purpose — it just returns a named logger
that writes readable, timestamped lines to the console.
"""

import logging

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """Return a logger with a consistent format, configuring the root once."""
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )
        _CONFIGURED = True
    return logging.getLogger(name)
