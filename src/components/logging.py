"""Project logging setup."""

import logging

from src.components import config


def get_logger(name):
    """Return a configured logger for one module."""
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    return logging.getLogger(name)
