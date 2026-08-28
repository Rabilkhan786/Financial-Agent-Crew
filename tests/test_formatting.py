"""Tests for formatting.py.

Had no tests before this. The one worth getting right is evidence_for(): if a
metric name in ratios.py or kpi.py drifts from the EVIDENCE table (a rename, a
new ratio added, an old one removed), the app would silently show "-" for
Period/Source/Formula on a real number instead of failing loudly. Checking
that every metric the maths layer actually produces has a real entry catches
that the same way test_ratios.py's import check catches a different kind of
drift.
"""

from src import formatting
from src.tools import kpi, ratios


def test_label_has_a_friendly_name_for_a_known_metric():
    assert formatting.label("operating_margin") == "Operating margin"


def test_label_falls_back_to_a_readable_default_for_an_unknown_metric():
    assert formatting.label("some_new_thing") == "Some new thing"


def test_money_shortens_large_amounts():
    assert formatting.money(1_500_000_000, "USD") == "USD 1.50bn"
    assert formatting.money(2_500_000, "USD") == "USD 2.5m"
    assert formatting.money(None) == "unavailable"


def test_metric_formats_percentages_and_plain_numbers_differently():
    assert formatting.metric("operating_margin", 0.207) == "20.7%"
    assert formatting.metric("debt_to_equity", 0.4444) == "0.44"
    assert formatting.metric("operating_margin", None) == "unavailable"


def test_facts_block_lists_every_metric_given():
    block = formatting.facts_block({"operating_margin": 0.2, "debt_to_equity": 0.5})
    assert "Operating margin" in block
    assert "Debt to equity" in block


# --- evidence_for(): the one that must not silently drift -------------------

def test_evidence_for_a_known_metric_has_all_three_fields():
    result = formatting.evidence_for("operating_margin")
    assert result["period"] and result["source"] and result["formula"]
    assert "revenue" in result["formula"]


def test_evidence_for_an_unknown_metric_degrades_rather_than_raising():
    result = formatting.evidence_for("something_that_does_not_exist")
    assert result == {"period": "-", "source": "Yahoo Finance", "formula": "-"}


def test_every_fundamental_ratio_has_a_real_evidence_entry():
    # ALL_RATIOS is what fundamentals_analyst actually computes and shows;
    # revenue_cagr is computed alongside it in compute_all() but lives outside
    # the dict itself.
    names = list(ratios.ALL_RATIOS) + ["revenue_cagr"]
    for name in names:
        assert name in formatting.EVIDENCE, f"{name} has no evidence entry"


def test_every_price_kpi_has_a_real_evidence_entry():
    # compute_all(None) still returns every key "latest" would ever have, just
    # with None values - exactly the real key set, with no network needed.
    result = kpi.compute_all(None)
    for name in result["latest"]:
        assert name in formatting.EVIDENCE, f"{name} has no evidence entry"
