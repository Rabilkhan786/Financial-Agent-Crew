"""Check that LLM prose only quotes numbers Python actually computed.

CHANGE 2's rule is that every figure comes from a deterministic Python function and
the LLM merely explains it. A prompt asking the model to "use only these findings"
is a request, not a guarantee — this module is the enforcement. We pull the numbers
out of the model's sentences and confirm each one traces back to a real finding.

Deliberately tolerant about *form*, strict about *value*: "65.5%", "65.47%" and
"66%" should all pass against a computed 65.47, because rounding in prose is fine.
Inventing 80% is not.
"""

import re

# Numbers as they appear in prose: 65.5, -3.45, 1,234.5, 2.87 ... optional % or x.
_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")

# Small integers are almost always counts ("3 news items", "2 rounds", "10-question
# checklist") or years, not financial claims. Checking them creates noise without
# catching fabrication, so they're ignored.
_TRIVIAL_MAX = 12
_YEAR_MIN, _YEAR_MAX = 1900, 2100


def extract_numbers(text: str) -> list[float]:
    """Every number in the text that could plausibly be a financial claim."""
    found = []
    for raw in _NUMBER_PATTERN.findall(text):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if abs(value) <= _TRIVIAL_MAX:
            continue  # counts, small round numbers
        if _YEAR_MIN <= value <= _YEAR_MAX and float(value).is_integer():
            continue  # a year, not a metric
        found.append(value)
    return found


def _allowed_forms(value: float) -> set[float]:
    """The ways one computed value may legitimately be written in prose.

    A ratio of 0.6547 is normally written "65.5%", and a raw 2_868_000_000 as
    "2.87B", so the same underlying number has several honest surface forms.
    """
    forms = {value, round(value, 2), round(value, 1), round(value)}
    scaled = value * 100  # a fraction quoted as a percentage
    forms |= {scaled, round(scaled, 2), round(scaled, 1), round(scaled)}
    for divisor in (1e3, 1e6, 1e9, 1e12):  # thousands / millions / billions
        if abs(value) >= divisor:
            shrunk = value / divisor
            forms |= {round(shrunk, 2), round(shrunk, 1), round(shrunk)}
    return {abs(f) for f in forms}


def unsupported_numbers(text: str, allowed_values: list[float], tolerance: float = 0.02) -> list[float]:
    """Numbers in ``text`` that don't match any computed value. Empty == clean.

    ``tolerance`` is relative, so a prose figure rounded to 2 significant places
    still matches the exact computed one.
    """
    permitted: set[float] = set()
    for value in allowed_values:
        permitted |= _allowed_forms(value)

    unsupported = []
    for number in extract_numbers(text):
        target = abs(number)
        if any(
            abs(target - ok) <= max(tolerance * max(abs(ok), 1e-9), 0.011)
            for ok in permitted
        ):
            continue
        unsupported.append(number)
    return unsupported


def verify_summary(text: str, allowed_values: list[float]) -> tuple[bool, list[float]]:
    """(is_clean, offending_numbers) for a piece of generated prose."""
    offenders = unsupported_numbers(text, allowed_values)
    return (not offenders, offenders)
