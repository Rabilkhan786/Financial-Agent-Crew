"""The baseline: one LLM, one search, one pass — no specialists, no cross-check.

This is deliberately the *simple* way to answer an investment question, and it is
the bar InvestPanel has to clear. If the multi-agent panel can't beat this, the
extra complexity isn't earning its keep — and the project says to report that
honestly. Keeping the baseline here, runnable over the same question set with the
same metrics, is what makes the comparison fair.

The LLM and the search function are passed in (dependency injection) so tests can
supply fakes and never touch the network.
"""

import json
import time
from pathlib import Path

from pydantic import BaseModel

from investpanel import config
from investpanel.llm.factory import get_llm
from investpanel.tools import search
from investpanel.utils.tracing import save_trace

SYSTEM_NAME = "Single LLM + search"


class BaselineAnswer(BaseModel):
    """The baseline's structured answer — shaped so the metrics can consume it."""

    question_id: str
    conclusion: str  # the analysis / the system's "reasonable read"
    flagged_contradiction: bool  # did it notice any tension in the evidence?
    contradiction_note: str | None = None
    firm_conclusion: bool  # a firm view, vs "insufficient evidence"
    sources: list[str] = []  # URLs it drew on — even the baseline should cite
    latency_seconds: float = 0.0


# The single prompt the baseline uses. It asks for JSON so the answer is
# structured enough to score, mirroring what the panel produces via its models.
BASELINE_PROMPT = """You are an investment research assistant. Using ONLY the search
results provided, analyse the question. Judge the QUALITY of the company as an
investment based on the evidence; do NOT predict the future stock price.

Return ONLY a JSON object with these exact keys:
  "conclusion": a few sentences of balanced analysis,
  "flagged_contradiction": true if the evidence contains a real internal tension
      (e.g. strong financials but a serious qualitative red flag), else false,
  "contradiction_note": one sentence describing that tension, or null,
  "firm_conclusion": true if you are giving a firm view, false if the evidence is
      insufficient to conclude,
  "sources": a list of the result URLs you actually relied on.

QUESTION:
{question}

SEARCH RESULTS (JSON):
{results}
"""


def _parse_json(text: str) -> dict:
    """Parse the model's reply into a dict, tolerating ```json code fences.

    Models often wrap JSON in markdown fences; we strip those before parsing so a
    cosmetic wrapper doesn't cause a hard failure.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop the first fence line and any trailing fence.
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.removeprefix("json").strip()
    return json.loads(cleaned)


def run_baseline(question, llm=None, searcher=None) -> BaselineAnswer:
    """Answer one HeldoutQuestion with the single-LLM-plus-search baseline.

    ``question`` is a HeldoutQuestion. ``llm`` and ``searcher`` default to the
    real Gemini model and Tavily search, but tests pass fakes instead.
    """
    llm = llm or get_llm()
    searcher = searcher or search.search_news

    start = time.perf_counter()

    # One search, using the company name and the question's focus.
    raw = searcher(f"{question.company} investment analysis fundamentals news", max_results=5)
    results = raw.get("results", [])

    prompt = BASELINE_PROMPT.format(
        question=question.question,
        results=json.dumps(results, indent=2),
    )
    reply = llm.invoke(prompt)
    text = getattr(reply, "content", str(reply))
    parsed = _parse_json(text)

    latency = time.perf_counter() - start

    answer = BaselineAnswer(
        question_id=question.id,
        conclusion=parsed.get("conclusion", ""),
        flagged_contradiction=bool(parsed.get("flagged_contradiction", False)),
        contradiction_note=parsed.get("contradiction_note"),
        firm_conclusion=bool(parsed.get("firm_conclusion", False)),
        sources=parsed.get("sources", []) or [],
        latency_seconds=round(latency, 3),
    )

    # Every run leaves a local trace, from Phase 0 onward.
    save_trace(
        "baseline_answer",
        {"question_id": question.id, "answer": answer.model_dump(mode="json")},
    )
    return answer


def run_over_questions(questions=None, llm=None, judge=None, out_path: Path | None = None):
    """Run the baseline over the whole question set and write one scored row.

    This is GATE 2: it produces the "Single LLM + search" row of the results
    table with real numbers. It needs live API keys (Gemini + Tavily), so it is
    not exercised by the test suite — the pieces it calls are each unit-tested
    with fakes instead. Returns the EvalSummary.
    """
    # Imported here (not at module top) so importing this module for the unit
    # tests never pulls in the whole eval stack.
    from eval.datasets.heldout_questions import QUESTIONS
    from eval.metrics import build_question_result, make_llm_judge, summarize

    questions = questions if questions is not None else QUESTIONS
    llm = llm or get_llm()
    judge = judge or make_llm_judge(get_llm())
    out_path = out_path or (config.PROJECT_ROOT / "eval" / "results" / "baseline.json")

    results = []
    for q in questions:
        answer = run_baseline(q, llm=llm)
        result = build_question_result(
            question_id=q.id,
            question_text=q.question,
            reasonable_read=q.reasonable_read,
            had_known_contradiction=q.has_known_contradiction,
            conclusion=answer.conclusion,
            flagged_contradiction=answer.flagged_contradiction,
            firm_conclusion=answer.firm_conclusion,
            judge=judge,
            latency_seconds=answer.latency_seconds,
        )
        results.append(result)
        print(f"  scored {q.id}: quality={result.reasoning_quality:.2f}")

    summary = summarize(SYSTEM_NAME, results)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary.as_dict(), indent=2), encoding="utf-8")
    print(f"\nWrote baseline results to {out_path}")
    print(json.dumps(summary.as_dict(), indent=2))
    return summary


def main() -> None:
    run_over_questions()


if __name__ == "__main__":
    main()
