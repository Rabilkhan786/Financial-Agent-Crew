"""Tests for the eval's result classification.

evals/run_eval.py had no tests before this: it is the one place that decides
whether a company's row in the results table means "the crew got something
wrong" or "the free tier ran out of tokens for the day." Getting that
distinction wrong would make a healthy crew look broken, or a broken one look
fine, so it is worth testing directly against synthetic inputs rather than
only trusting it because a live run happened to look right once.
"""

from evals.run_eval import STUB_REPORT_MARKER, classify


def row(report="## Executive summary\nx", metrics=None, kpis=None,
        blanks=True, numbers=True, sections=True, crashed=None):
    """A result row holding only what classify() reads."""
    return {
        "report": report,
        "fundamentals": {"metrics": metrics if metrics is not None else {"operating_margin": 0.2}},
        "analysis": {"kpis": kpis if kpis is not None else {"total_return": 0.1}},
        "no_blanks": {"passed": blanks},
        "no_invented_numbers": {"passed": numbers},
        "sections_present": {"passed": sections},
        "crashed": crashed,
    }


def test_a_clean_report_passes():
    assert classify(row()) == "PASS"


def test_a_crash_is_fail_regardless_of_anything_else():
    assert classify(row(crashed="boom", blanks=False)) == "FAIL"


def test_a_stub_report_is_provider_limit_not_a_plain_fail():
    # This is the exact text report_writer.py writes when the model never
    # answers - classify() must recognise it by the same constant, not a copy.
    stub = f"## Executive summary\n\n{STUB_REPORT_MARKER} more text."
    assert classify(row(report=stub, sections=False)) == "PROVIDER_LIMIT"


def test_provider_limit_beats_data_unavailable():
    # A stub report with no metrics either: the model not answering is the
    # more specific, more useful thing to say happened.
    stub = f"## Executive summary\n\n{STUB_REPORT_MARKER}"
    assert classify(row(report=stub, metrics={}, kpis={}, sections=False)) == "PROVIDER_LIMIT"


def test_no_metrics_and_no_kpis_is_data_unavailable():
    assert classify(row(metrics={}, kpis={}, sections=False)) == "DATA_UNAVAILABLE"


def test_metrics_present_but_no_kpis_is_not_data_unavailable():
    # Statements came back but prices did not (or the reverse) - that is a
    # partial result, not "Yahoo had nothing," so it falls through to the
    # ordinary three checks.
    assert classify(row(kpis={}, sections=False)) == "FAIL"
    assert classify(row(kpis={})) == "PASS"


def test_a_failed_check_with_real_data_is_a_plain_fail():
    assert classify(row(numbers=False)) == "FAIL"
    assert classify(row(sections=False)) == "FAIL"
    assert classify(row(blanks=False)) == "FAIL"
