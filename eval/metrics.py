"""Metrics — how we score a system's answers against the ground truth.

Four things the project cares about, plus cost and latency:

1. Reasoning quality — how sound is the analysis versus the documented
   "reasonable read"? Scored 1-5 by an LLM judge against a fixed rubric, then
   normalized to 0-1. The judge is passed in as a function so tests can supply a
   fake one (no test ever makes a real API call).
2. Contradiction catch rate — of the questions we labeled as containing a real
   tension, how many did the system actually flag? (a recall measure).
3. Confidently-wrong rate — how often the system gave a firm conclusion that
   contradicts the reasonable read. Being confidently wrong is worse than saying
   "insufficient evidence", so we track it as a headline number.
4. Cost and latency per question — averaged across the run.

The aggregation in ``summarize`` takes a list of per-question results with known
numbers, so it can be unit-tested against a fixture with a known expected output.
"""

from collections.abc import Callable
from dataclasses import dataclass

# The fixed rubric the LLM judge is told to apply. Kept as a constant so the
# scoring is consistent across runs and can be quoted in docs/evaluation.md.
REASONING_RUBRIC = """You are grading the QUALITY OF REASONING in an investment analysis,
NOT whether the stock later went up or down. Give an integer score from 1 to 5:

5 - Sound, evidence-based, weighs both sides, matches the reasonable read, and is
    honest about uncertainty.
4 - Mostly sound with minor gaps.
3 - Mixed: some good points but misses an important consideration in the reasonable read.
2 - Weak: superficial, one-sided, or ignores key known risks.
1 - Poor: unsupported, contradicts the known context, or overconfident and wrong.

Reply with ONLY the single digit 1-5."""

# A judge is any function that, given the question, the system's answer, and the
# reasonable read, returns an integer 1-5.
Judge = Callable[[str, str, str], int]


def score_reasoning(question: str, system_answer: str, reasonable_read: str, judge: Judge) -> float:
    """Return a 0-1 reasoning-quality score using the supplied judge.

    We normalize the judge's 1-5 to 0-1 so it combines cleanly with the other
    rates. Anything outside 1-5 is clamped, so a misbehaving judge can't produce
    a nonsense score.
    """
    raw = judge(question, system_answer, reasonable_read)
    raw = max(1, min(5, int(raw)))
    return (raw - 1) / 4  # 1 -> 0.0, 5 -> 1.0


def make_llm_judge(llm) -> Judge:
    """Wrap a chat model into a Judge function that applies REASONING_RUBRIC.

    Used in the real evaluation; tests pass their own fake judge instead, so this
    wrapper (which would call the model) is never exercised by the test suite.
    """

    def judge(question: str, system_answer: str, reasonable_read: str) -> int:
        prompt = (
            f"{REASONING_RUBRIC}\n\n"
            f"QUESTION:\n{question}\n\n"
            f"REASONABLE READ (the benchmark):\n{reasonable_read}\n\n"
            f"SYSTEM'S ANSWER TO GRADE:\n{system_answer}\n"
        )
        reply = llm.invoke(prompt)
        text = getattr(reply, "content", str(reply))
        return _parse_score(text)

    return judge


def _parse_score(text: str) -> int:
    """Pull the first 1-5 digit out of the judge's reply; default to 1 if none.

    Defaulting to the lowest score means a garbled judge reply can never inflate
    a system's result — it fails safe toward "poor".
    """
    for char in text.strip():
        if char in "12345":
            return int(char)
    return 1


@dataclass
class QuestionResult:
    """Everything we need to know about how the system did on ONE question."""

    question_id: str
    reasoning_quality: float  # 0-1, from score_reasoning
    had_known_contradiction: bool  # label from the dataset
    caught_contradiction: bool  # did the system flag a contradiction here?
    gave_firm_conclusion: bool  # did the system commit to a firm view?
    contradicts_reasonable_read: bool  # was that view against the reasonable read?
    cost_usd: float = 0.0
    latency_seconds: float = 0.0


@dataclass
class EvalSummary:
    """Aggregate numbers across a whole run — the row that goes in the README."""

    system_name: str
    num_questions: int
    mean_reasoning_quality: float
    contradiction_catch_rate: float | None  # None if no labeled contradictions
    confidently_wrong_rate: float
    mean_cost_usd: float
    mean_latency_seconds: float
    num_labeled_contradictions: int
    num_contradictions_caught: int

    def as_dict(self) -> dict:
        return {
            "system_name": self.system_name,
            "num_questions": self.num_questions,
            "mean_reasoning_quality": round(self.mean_reasoning_quality, 4),
            "contradiction_catch_rate": (
                None if self.contradiction_catch_rate is None
                else round(self.contradiction_catch_rate, 4)
            ),
            "confidently_wrong_rate": round(self.confidently_wrong_rate, 4),
            "mean_cost_usd": round(self.mean_cost_usd, 6),
            "mean_latency_seconds": round(self.mean_latency_seconds, 3),
            "num_labeled_contradictions": self.num_labeled_contradictions,
            "num_contradictions_caught": self.num_contradictions_caught,
        }


def summarize(system_name: str, results: list[QuestionResult]) -> EvalSummary:
    """Combine per-question results into one summary. Fixture-testable by design."""
    if not results:
        raise ValueError("Cannot summarize an empty results list.")

    n = len(results)
    mean_quality = sum(r.reasoning_quality for r in results) / n

    # Catch rate = caught / labeled, but only over questions we actually labeled.
    labeled = [r for r in results if r.had_known_contradiction]
    caught = sum(1 for r in labeled if r.caught_contradiction)
    catch_rate = (caught / len(labeled)) if labeled else None

    # Confidently wrong = firm conclusion AND it contradicts the reasonable read.
    confidently_wrong = sum(
        1 for r in results if r.gave_firm_conclusion and r.contradicts_reasonable_read
    )
    confidently_wrong_rate = confidently_wrong / n

    mean_cost = sum(r.cost_usd for r in results) / n
    mean_latency = sum(r.latency_seconds for r in results) / n

    return EvalSummary(
        system_name=system_name,
        num_questions=n,
        mean_reasoning_quality=mean_quality,
        contradiction_catch_rate=catch_rate,
        confidently_wrong_rate=confidently_wrong_rate,
        mean_cost_usd=mean_cost,
        mean_latency_seconds=mean_latency,
        num_labeled_contradictions=len(labeled),
        num_contradictions_caught=caught,
    )
