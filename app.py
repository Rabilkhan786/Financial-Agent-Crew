"""Streamlit demo for InvestPanel.

Two tabs:
  - Research: type a question, watch the panel research a company, and see a
    full research dashboard — executive summary, the 10-question checklist in
    plain English, financial/risk/news detail, peer comparison, and the
    analyst's cross-check (what's consistent, what's a tension worth watching,
    and what's a confirmed contradiction) — with the disclaimer always shown.
    The report can be downloaded as a Markdown file.
  - Observability: reads the local JSON traces from every run so far and shows
    aggregate behaviour (how often the follow-up loop fired, average latency,
    average checklist completeness) — the tracing data made visible.

All formatting and classification logic lives in investpanel.utils — this file
only renders what those pure functions hand it; it makes no API or LLM calls
of its own.

Run it with:  uv run streamlit run app.py   (needs the four API keys in .env)
"""

import streamlit as st

from investpanel import config
from investpanel.models.report import DISCLAIMER_TEXT
from investpanel.utils.report_analysis import (
    SOURCE_LABELS,
    build_executive_summary,
    build_human_checklist,
    build_peer_table,
    build_risk_summary,
    contradiction_status,
    crosscheck_conclusion,
    data_freshness,
    evidence_quality,
    missing_evidence_rows,
    peer_comparison_note,
)
from investpanel.utils.report_export import report_to_markdown
from investpanel.utils.report_format import format_metric_label, format_metric_value
from investpanel.utils.trace_stats import summarize_panel_runs

st.set_page_config(page_title="InvestPanel", page_icon="📊", layout="wide")

st.title("📊 InvestPanel")
st.caption("A multi-agent research panel that cross-checks its own findings before concluding.")
# The disclaimer is shown prominently near the top, never buried.
st.warning(DISCLAIMER_TEXT)

research_tab, obs_tab = st.tabs(["Research a company", "Observability"])

# The headline metrics shown as a quick-glance row, when available.
_KEY_METRICS = ["pe_ratio", "revenue_growth", "profit_growth", "debt_to_equity", "annualized_volatility"]


def _render_report(report) -> None:
    # --- Company header + research metadata -------------------------------------
    header = report.company + (f" ({report.ticker})" if report.ticker else "")
    st.header(header)
    freshness = data_freshness(report)
    st.caption(
        f"Researched {freshness['Research date']} · Financial data: {freshness['Financial data period']} "
        f"· News: {freshness['News coverage window']} · Price history: {freshness['Price/risk analysis window']}"
    )

    # --- Executive summary ----------------------------------------------------------
    st.subheader("Executive Summary")
    exec_summary = build_executive_summary(report)
    cols = st.columns(len(exec_summary))
    for col, (category, rating) in zip(cols, exec_summary.items(), strict=True):
        col.metric(category, rating)
    quality = evidence_quality(report, report.ticker)
    st.caption(
        f"Evidence quality — Overall: **{quality['Overall']}** · Financial: {quality['Financial']} "
        f"· News: {quality['News']} · Risk: {quality['Risk']} · Peer comparison: {quality['Peer comparison']}"
    )
    st.info(f"**Key Takeaway:** {report.summary}")
    st.markdown(f"**What it does (Q1):** {report.company_description}")

    # --- Key metrics quick-glance row -------------------------------------------------
    by_metric = {f.metric: f for f in report.financial_findings}
    by_metric.update({f.metric: f for f in report.risk_findings})
    available = [m for m in _KEY_METRICS if m in by_metric]
    if available:
        st.subheader("Key Metrics")
        cols = st.columns(len(available))
        for col, metric in zip(cols, available, strict=True):
            finding = by_metric[metric]
            col.metric(format_metric_label(metric), format_metric_value(metric, finding.value))

    # --- 10-question checklist --------------------------------------------------------
    st.subheader("10-Question Checklist")
    checklist_rows = build_human_checklist(report)
    st.dataframe(
        [
            {"Question": r["question"], "Result": r["result"], "Status": r["status"],
             "Why it matters": r["why_it_matters"]}
            for r in checklist_rows
        ],
        width="stretch", hide_index=True,
    )

    # --- Financial analysis -------------------------------------------------------------
    with st.expander("Financial Analysis — every metric with its source"):
        if report.financial_findings:
            st.dataframe(
                [
                    {"Metric": format_metric_label(f.metric), "Value": format_metric_value(f.metric, f.value),
                     "Status": "Healthy" if f.healthy else "Concern", "Source": f.source}
                    for f in report.financial_findings
                ],
                width="stretch", hide_index=True,
            )
        else:
            st.write("Insufficient evidence — no financial metrics could be computed.")

    # --- Risk analysis -----------------------------------------------------------------
    st.subheader("Risk Analysis")
    risk_rows = build_risk_summary(report.risk_findings)
    if risk_rows:
        cols = st.columns(len(risk_rows))
        for col, row in zip(cols, risk_rows, strict=True):
            col.metric(row["metric"], row["value"])
        for row in risk_rows:
            st.caption(f"**{row['metric']}:** {row['interpretation']} (from {row['computed_from']})")
    else:
        st.write("Insufficient evidence — no price history was available.")

    # --- News analysis -----------------------------------------------------------------
    st.subheader("News Analysis")
    st.caption(f"{len(report.news_findings)} article(s) reviewed · coverage window: "
               f"{freshness['News coverage window']}")
    if report.news_findings:
        for n in report.news_findings:
            with st.expander(n.headline):
                st.markdown(f"**What happened:** {n.summary}")
                why = f"Relevance: {n.relevance}" + (
                    f", tagged as {n.checklist_question}" if n.checklist_question else ""
                )
                st.markdown(f"**Why it matters:** {why}")
                st.markdown(f"**Published:** {n.published_date.isoformat()}")
                st.markdown(f"**Source:** [{n.source_url}]({n.source_url})")
    else:
        st.write("Insufficient evidence — no sourced articles were available.")

    # --- Peer comparison -----------------------------------------------------------------
    st.subheader("Peer Comparison")
    peer_rows = build_peer_table(report.peer_comparison)
    note = peer_comparison_note(report)
    if peer_rows:
        columns = sorted({k for row in peer_rows for k in row if k != "Metric"})
        st.dataframe(
            [{"Metric": row["Metric"], **{c: row.get(c, "—") for c in columns}} for row in peer_rows],
            width="stretch", hide_index=True,
        )
        if note:
            st.caption(note)
    else:
        st.warning(f"**Peer comparison unavailable** — {note}")

    # --- Analyst cross-check ---------------------------------------------------------------
    st.subheader("Analyst Cross-Check")
    status, explanation = crosscheck_conclusion(report)
    if status == "Cross-check not possible":
        # Never claim "consistent" when there was nothing to compare.
        st.warning(f"**{status}** — {explanation}")
    elif status == "Consistent evidence":
        st.success(f"**{status}** — {explanation}")
    if report.potential_tensions:
        st.markdown("**Potential Tensions** — worth a second look, not confirmed conflicts")
        for t in report.potential_tensions:
            st.markdown(
                f"- **{t.between[0]} vs {t.between[1]}** — {t.description}\n\n"
                f"  *Why this isn't a confirmed contradiction:* {t.reason}"
            )
    if report.contradictions_found:
        st.markdown("**Confirmed Contradictions**")
        st.info(f"Found {len(report.contradictions_found)}; "
                f"follow-up round(s) run: {report.contradictions_resolved} "
                f"(capped at {config.MAX_FOLLOWUP_ROUNDS}).")
        for c in report.contradictions_found:
            status = contradiction_status(report, c)
            with st.expander(f"{c.between[0]} vs {c.between[1]} — {c.description[:80]}"):
                st.markdown(f"**Source A:** {SOURCE_LABELS.get(c.between[0], c.between[0])}")
                st.markdown(f"**Source B:** {SOURCE_LABELS.get(c.between[1], c.between[1])}")
                st.markdown(f"**Why they conflict:** {c.description}")
                st.markdown(f"**Follow-up question asked:** {c.follow_up_question}")
                st.markdown(f"**Status:** {status}")

    # --- Missing evidence ------------------------------------------------------------------
    missing = missing_evidence_rows(report)
    with st.expander(f"Missing Evidence ({len(missing)})"):
        if missing:
            for row in missing:
                st.markdown(f"**{row['question']}**")
                st.write(
                    "Insufficient evidence. The system could not obtain enough reliable data "
                    "to answer this question."
                )
                st.caption(f"Reason: {row['missing_reason']}")
        else:
            st.write("None — every checklist question was answered with sourced evidence.")

    # --- Data freshness ----------------------------------------------------------------------
    with st.expander("Data Freshness"):
        for label, value in freshness.items():
            st.write(f"**{label}:** {value}")

    # --- Sources -------------------------------------------------------------------------------
    with st.expander("Sources"):
        for f in report.financial_findings:
            st.write(f"Financial · {f.metric}: {f.source}")
        for r in report.risk_findings:
            st.write(f"Risk · {r.metric}: {r.computed_from}")
        for n in report.news_findings:
            st.write(f"News · {n.headline}: {n.source_url}")

    # --- Disclaimer, always, at the end of the report too --------------------------------------
    st.divider()
    st.caption(report.disclaimer)

    st.download_button(
        "⬇ Download this report (Markdown)",
        data=report_to_markdown(report),
        file_name=f"investpanel_{report.company.replace(' ', '_')}.md",
        mime="text/markdown",
    )


with research_tab:
    question = st.text_input(
        "Investment question",
        value="Is Apple a reasonable long-term investment?",
    )
    if st.button("Research", type="primary"):
        with st.spinner("The panel is researching… (manager → specialists → analyst)"):
            try:
                # Imported here so the app loads even before keys are set.
                from investpanel.graph.workflow import run_panel

                report = run_panel(question)
                _render_report(report)
            except Exception as error:  # noqa: BLE001 - show any run error to the user, don't crash the app
                st.error(f"Could not complete the run: {error}")
                st.info("Check that all four API keys are set in your .env file.")


with obs_tab:
    st.markdown("### Behaviour across every run so far")
    stats = summarize_panel_runs(config.TRACE_DIR)
    if stats["num_runs"] == 0:
        st.write("No runs recorded yet. Research a company to populate this dashboard.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Runs", stats["num_runs"])
        c2.metric("Follow-up loop fired", f"{stats['loop_fire_rate'] * 100:.0f}%")
        c3.metric("Avg latency", f"{stats['avg_latency_seconds']:.1f}s")
        c4.metric("Avg checklist completeness", f"{stats['avg_checklist_completeness'] * 100:.0f}%")
        st.markdown("#### Per-run detail")
        st.dataframe(stats["runs"])
