"""Tests for the Pydantic models — especially the two rules enforced in code.

No network, no LLM. These prove the schema itself enforces the project's hard
rules: a news claim cannot exist without a source, and the report disclaimer
cannot be weakened or removed by any code path.
"""

import pytest
from pydantic import ValidationError

from investpanel.models import DISCLAIMER_TEXT, NewsFinding, Report


def test_newsfinding_requires_a_source_url():
    # Leaving out source_url must fail — this is the no-unsourced-facts rule.
    with pytest.raises(ValidationError):
        NewsFinding(
            headline="Company does a thing",
            summary="A short summary in our own words.",
            published_date="2025-01-01",
            relevance="high",
        )


def test_newsfinding_rejects_a_non_url_source():
    with pytest.raises(ValidationError):
        NewsFinding(
            headline="Company does a thing",
            summary="A short summary.",
            source_url="not-a-real-url",
            published_date="2025-01-01",
            relevance="high",
        )


def test_report_always_has_the_canonical_disclaimer():
    r = Report(company="Acme", company_description="Makes widgets.", summary="Fine.")
    assert r.disclaimer == DISCLAIMER_TEXT


def test_report_forces_disclaimer_even_if_an_agent_passes_a_fake_one():
    # An agent trying to weaken the disclaimer must be overridden by the validator.
    r = Report(
        company="Acme",
        company_description="Makes widgets.",
        summary="Fine.",
        disclaimer="This is definitely investment advice, go all in!",
    )
    assert r.disclaimer == DISCLAIMER_TEXT


def test_report_disclaimer_cannot_be_mutated_after_creation():
    r = Report(company="Acme", company_description="Makes widgets.", summary="Fine.")
    # frozen=True on the field means reassignment raises.
    with pytest.raises(ValidationError):
        r.disclaimer = "hacked"
