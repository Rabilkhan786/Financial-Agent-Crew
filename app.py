"""Streamlit demo for InvestPanel.

Two tabs:
  - Research: type a question, watch the panel research a company, and see the
    three specialists' findings, any contradiction the analyst caught and the
    follow-up it sent, and the final report — with the disclaimer shown up top.
    The report can be downloaded as a Markdown file.
  - Observability: reads the local JSON traces from every run so far and shows
    aggregate behaviour (how often the follow-up loop fired, average latency,
    average checklist completeness) — the tracing data made visible.

Run it with:  uv run streamlit run app.py   (needs the four API keys in .env)
"""

import streamlit as st

from investpanel import config
from investpanel.models.report import DISCLAIMER_TEXT
from investpanel.utils.report_export import report_to_markdown
from investpanel.utils.trace_stats import summarize_panel_runs

st.set_page_config(page_title="InvestPanel", page_icon="📊", layout="wide")

st.title("📊 InvestPanel")
st.caption("A multi-agent research panel that cross-checks its own findings before concluding.")
# The disclaimer is shown prominently near the top, never buried.
st.warning(DISCLAIMER_TEXT)

research_tab, obs_tab = st.tabs(["Research a company", "Observability"])


def _render_report(report) -> None:
    st.subheader(report.company)
    st.markdown(f"**What it does (Q1):** {report.company_description}")
    st.markdown(f"**Summary:** {report.summary}")

    st.markdown("### 10-question checklist")
    st.table(
        [{"question": k, "answer": v} for k, v in sorted(report.checklist_answers.items())]
    )

    if report.peer_comparison:
        st.markdown("### Peer comparison")
        st.dataframe(report.peer_comparison)

    st.markdown("### Contradictions caught by the analyst")
    if report.contradictions_found:
        st.info(f"Caught {len(report.contradictions_found)} contradiction(s); "
                f"ran {report.contradictions_resolved} follow-up round(s).")
        for c in report.contradictions_found:
            st.markdown(
                f"- **{c.between[0]} vs {c.between[1]}** — {c.description}  \n"
                f"  ↳ asked **{c.follow_up_target}**: _{c.follow_up_question}_"
            )
    else:
        st.write("No contradictions found — the findings were consistent.")

    with st.expander("All findings with sources"):
        for f in report.financial_findings:
            st.write(f"**Financial · {f.metric}** = {f.value} {f.unit} "
                     f"({'healthy' if f.healthy else 'concern'}) — source: {f.source}")
        for r in report.risk_findings:
            st.write(f"**Risk · {r.metric}** = {r.value} — {r.computed_from}")
        for n in report.news_findings:
            st.write(f"**News · {n.headline}** ({n.published_date}) — {n.source_url}")

    st.download_button(
        "⬇️ Download this report (Markdown)",
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
