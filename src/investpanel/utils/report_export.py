"""Turn a Report into a single Markdown document for download.

The Streamlit app lets a user save one company's report as a static file. Keeping
the formatting here (a pure function) means it can be unit-tested and reused, and
guarantees the exported file ends with the same disclaimer as everything else.
"""

from investpanel.models.report import Report

# The 10 checklist questions in plain English, for headings in the export.
_CHECKLIST_LABELS = {
    "q2": "Is revenue growing?",
    "q3": "Are profits growing?",
    "q4": "Is operating cash flow healthy?",
    "q5": "Is debt manageable?",
    "q6": "Are ROCE / ROE healthy?",
    "q7": "Durable competitive advantage?",
    "q8": "Is management trustworthy / shareholder-friendly?",
    "q9": "What could seriously damage the business?",
    "q10": "Is the price reasonable vs future earnings?",
}


def report_to_markdown(report: Report) -> str:
    """Render a Report as Markdown text, ending with the disclaimer."""
    lines: list[str] = []
    lines.append(f"# InvestPanel report — {report.company}")
    lines.append("")
    lines.append("## What the company does (Q1)")
    lines.append(report.company_description or "Description unavailable.")
    lines.append("")
    lines.append("## Summary")
    lines.append(report.summary)
    lines.append("")

    lines.append("## 10-question checklist")
    lines.append("")
    lines.append("| # | Question | Answer |")
    lines.append("|---|---|---|")
    for key, label in _CHECKLIST_LABELS.items():
        answer = report.checklist_answers.get(key, "insufficient evidence")
        lines.append(f"| {key} | {label} | {answer} |")
    lines.append("")

    if report.peer_comparison:
        lines.append("## Peer comparison")
        lines.append("")
        for metric, values in report.peer_comparison.items():
            pairs = ", ".join(f"{name}: {value}" for name, value in values.items())
            lines.append(f"- **{metric}** — {pairs}")
        lines.append("")

    lines.append("## Contradictions found by the analyst")
    lines.append(f"Found {len(report.contradictions_found)}; "
                 f"follow-ups run: {report.contradictions_resolved}.")
    for c in report.contradictions_found:
        lines.append(f"- **{c.between[0]} vs {c.between[1]}** — {c.description} "
                     f"(asked {c.follow_up_target}: {c.follow_up_question})")
    lines.append("")

    lines.append("## Sources")
    for f in report.financial_findings:
        lines.append(f"- Financial · {f.metric}: {f.source}")
    for r in report.risk_findings:
        lines.append(f"- Risk · {r.metric}: {r.computed_from}")
    for n in report.news_findings:
        lines.append(f"- News · {n.headline}: {n.source_url}")
    lines.append("")

    lines.append("---")
    lines.append(f"_{report.disclaimer}_")
    return "\n".join(lines)
