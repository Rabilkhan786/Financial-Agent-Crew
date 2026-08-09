"""Pydantic models — the only things agents are allowed to pass to each other.

Re-exported here so callers can write ``from investpanel.models import Report``.
"""

from investpanel.models.contradiction import Contradiction
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding
from investpanel.models.report import DISCLAIMER_TEXT, Report
from investpanel.models.scope import ResearchScope

__all__ = [  # noqa: RUF022 — kept in pipeline order (scope -> findings -> report), not alphabetical
    "ResearchScope",
    "FinancialFinding",
    "NewsFinding",
    "RiskFinding",
    "Contradiction",
    "Report",
    "DISCLAIMER_TEXT",
]
