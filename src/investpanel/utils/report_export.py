"""Turn a Report into a single Markdown document for download.

The Streamlit app lets a user save one company's report as a static file. This
mirrors the same structure the app renders — executive summary, human-readable
checklist, facts vs interpretation, tensions vs contradictions, evidence quality,
data freshness — using the same formatting/analysis helpers so the two views
never drift apart. A pure function, so it's unit-tested and guarantees the
exported file ends with the same disclaimer as everything else.
"""

from investpanel.models.report import Report
from investpanel.utils.report_analysis import (
    SOURCE_LABELS,
    build_executive_summary,
    build_human_checklist,
    build_peer_table,
    build_risk_summary,
    contradiction_status,
    crosscheck_conclusion,
    data_freshness,
    empty_section_note,
    evidence_quality,
    missing_evidence_rows,
    peer_comparison_note,
    question_was_rewritten,
)
from investpanel.utils.report_format import format_metric_label, format_metric_value


def report_to_markdown(report: Report) -> str:
    """Render a Report as Markdown text, ending with the disclaimer."""
    lines: list[str] = []
    lines.append(f"# InvestPanel report — {report.company}")
    lines.append("")

    # --- Executive summary -----------------------------------------------------
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- **Company:** {report.company}")
    lines.append(f"- **Ticker:** {report.ticker or 'Unavailable'}")
    if question_was_rewritten(report):
        lines.append(f'- **Question asked:** "{report.question}"')
        lines.append(f'- **Interpreted as:** "{report.interpreted_question}"')
    freshness = data_freshness(report)
    for label, value in freshness.items():
        lines.append(f"- **{label}:** {value}")
    quality = evidence_quality(report, report.ticker)
    lines.append(f"- **Evidence quality (overall):** {quality['Overall']}")
    lines.append("")
    lines.append("| Category | Assessment |")
    lines.append("|---|---|")
    for category, rating in build_executive_summary(report).items():
        lines.append(f"| {category} | {rating} |")
    lines.append("")
    lines.append(f"**Key Takeaway:** {report.summary}")
    lines.append("")

    # --- Facts: what the company does -------------------------------------------
    lines.append("## What the company does (Q1)")
    lines.append(report.company_description or "Description unavailable.")
    lines.append("")

    # --- 10-question checklist ---------------------------------------------------
    lines.append("## 10-question checklist")
    lines.append("")
    lines.append("| Question | Result | Status | Why it matters |")
    lines.append("|---|---|---|---|")
    for row in build_human_checklist(report):
        lines.append(f"| {row['question']} | {row['result']} | {row['status']} | {row['why_it_matters']} |")
    lines.append("")

    # --- Financial analysis (facts) ----------------------------------------------
    lines.append("## Financial Analysis")
    lines.append("")
    if report.financial_findings:
        lines.append("| Metric | Value | Status | Source |")
        lines.append("|---|---|---|---|")
        for f in report.financial_findings:
            status = "Healthy" if f.healthy else "Concern"
            lines.append(
                f"| {format_metric_label(f.metric)} | {format_metric_value(f.metric, f.value)} "
                f"| {status} | {f.source} |"
            )
    else:
        lines.append(empty_section_note(report, "financial"))
    lines.append("")

    # --- Risk analysis ------------------------------------------------------------
    lines.append("## Risk Analysis")
    lines.append("")
    risk_rows = build_risk_summary(report.risk_findings)
    if risk_rows:
        for row in risk_rows:
            lines.append(f"- **{row['metric']}:** {row['value']} — {row['interpretation']}")
    else:
        lines.append(empty_section_note(report, "risk"))
    lines.append("")

    # --- News analysis --------------------------------------------------------------
    lines.append("## News Analysis")
    lines.append("")
    lines.append(f"Articles reviewed: {len(report.news_findings)}. "
                 f"Coverage window: {freshness['News coverage window']}.")
    lines.append("")
    for n in report.news_findings:
        lines.append(f"### {n.headline}")
        lines.append(f"**What happened:** {n.summary}")
        lines.append(f"**Why it matters:** relevance {n.relevance}"
                     + (f", tagged as {n.checklist_question}" if n.checklist_question else ""))
        lines.append(f"**Published:** {n.published_date.isoformat()}")
        lines.append(f"**Source:** {n.source_url}")
        lines.append("")
    if not report.news_findings:
        lines.append(empty_section_note(report, "news"))
        lines.append("")

    # --- Peer comparison --------------------------------------------------------------
    lines.append("## Peer comparison")
    lines.append("")
    peer_rows = build_peer_table(report.peer_comparison, report.ticker)
    note = peer_comparison_note(report)
    if peer_rows:
        columns = sorted({k for row in peer_rows for k in row if k != "Metric"})
        lines.append("| Metric | " + " | ".join(columns) + " |")
        lines.append("|---|" + "|".join("---" for _ in columns) + "|")
        for row in peer_rows:
            lines.append(f"| {row['Metric']} | " + " | ".join(row.get(c, "—") for c in columns) + " |")
        if note:
            lines.append("")
            lines.append(f"_Note: {note}_")
    else:
        lines.append(f"**Peer comparison unavailable** — {note}")
    lines.append("")

    # --- Analyst cross-check: consistent / tensions / contradictions --------------------
    lines.append("## Analyst Cross-Check")
    lines.append("")
    status, explanation = crosscheck_conclusion(report)
    if explanation:
        lines.append(f"**{status}** — {explanation}")
        lines.append("")
    if report.potential_tensions:
        lines.append("### Potential Tensions")
        lines.append("")
        for t in report.potential_tensions:
            lines.append(f"- **{t.between[0]} vs {t.between[1]}** — {t.description}  \n"
                         f"  *Reason this is a tension, not a contradiction:* {t.reason}")
        lines.append("")
    if report.contradictions_found:
        lines.append("### Confirmed Contradictions")
        lines.append(f"Found {len(report.contradictions_found)}; "
                     f"follow-up round(s) run: {report.contradictions_resolved}.")
        lines.append("")
        for c in report.contradictions_found:
            status = contradiction_status(report, c)
            lines.append(f"- **Source A:** {SOURCE_LABELS.get(c.between[0], c.between[0])}")
            lines.append(f"  **Source B:** {SOURCE_LABELS.get(c.between[1], c.between[1])}")
            lines.append(f"  **Why they conflict:** {c.description}")
            lines.append(f"  **Follow-up question asked:** {c.follow_up_question}")
            lines.append(f"  **Status:** {status}")
        lines.append("")

    # --- Additional findings (beyond the fixed checklist) -------------------------------
    if report.additional_findings:
        lines.append("## Additional Findings (beyond the 10-question checklist)")
        lines.append("")
        lines.append("_The checklist is the minimum every report covers. These are "
                     "materially relevant items no checklist question asked about._")
        lines.append("")
        for obs in report.additional_findings:
            lines.append(f"- **[{obs.severity.upper()}] {obs.title}** ({obs.source})  ")
            lines.append(f"  {obs.detail}  ")
            if obs.evidence:
                lines.append(f"  *Evidence:* {', '.join(obs.evidence)}")
        lines.append("")

    # --- Missing evidence --------------------------------------------------------------
    missing = missing_evidence_rows(report)
    lines.append("## Missing Evidence")
    lines.append("")
    if missing:
        for row in missing:
            lines.append(f"- **{row['question']}** — Insufficient evidence. "
                         f"The system could not obtain enough reliable data to answer this. "
                         f"Reason: {row['missing_reason']}")
    else:
        lines.append("None — every checklist question was answered with sourced evidence.")
    lines.append("")

    # --- Evidence quality --------------------------------------------------------------
    lines.append("## Evidence Quality")
    lines.append("")
    for source, rating in quality.items():
        if source != "Overall":
            lines.append(f"- **{source}:** {rating}")
    lines.append("")

    # --- Sources -------------------------------------------------------------------------
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
