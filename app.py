"""The Streamlit app: type a ticker, get a report.

Five tabs so the reader can go from the written report down to the raw numbers
that produced it.
"""

import datetime as dt

import pandas as pd
import streamlit as st

from src import config, formatting, graph, report_pdf

log = config.get_logger(__name__)

st.set_page_config(page_title="Financial Analysis Agent Crew", layout="wide",
                   initial_sidebar_state="expanded")

st.title("Financial Analysis Agent Crew")
st.caption("Five agents research a company and write a fundamental analysis report. "
           "Informational only - not investment advice.")


# --- Sidebar: what to analyse, and what is switched on ----------------------
with st.sidebar:
    st.header("Company")
    ticker = st.text_input("Ticker", value="AAPL",
                           help="A US listing, for example AAPL, MSFT or BA. "
                                "Other exchanges need a suffix, such as .L or .NS.")
    today = dt.date.today()
    start_date = st.date_input("From", value=today - dt.timedelta(days=365 * 3))
    end_date = st.date_input("To", value=today)
    run_it = st.button("Run the crew", type="primary", use_container_width=True)

    st.divider()
    st.subheader("Data sources")
    for name, switched_on in config.enabled_sources().items():
        st.write(("ON - " if switched_on else "off - ") + name)

    if config.missing_required():
        st.error("Missing in .env: " + ", ".join(config.missing_required()))


def metrics_table(values, currency=None):
    """Metric name, value, and the evidence behind it - period, source,
    formula - so a reader can check a figure without re-running the crew."""
    rows = []
    for name, value in values.items():
        evidence = formatting.evidence_for(name)
        rows.append({"Measure": formatting.label(name),
                     "Value": formatting.metric(name, value, currency),
                     "Period": evidence["period"],
                     "Source": evidence["source"],
                     "Formula": evidence["formula"]})
    return pd.DataFrame(rows)


DATA_SOURCE_LABEL = {
    "live": "🟢 live - fetched during this run",
    "cached": "🔵 cached - reused from an earlier fetch",
    "unavailable": "⚪ unavailable - nothing came back",
}


def data_source_caption(source):
    """One line saying whether a section's figures were fetched just now,
    reused from the disk cache, or never arrived - never left to guesswork."""
    st.caption(DATA_SOURCE_LABEL.get(source, DATA_SOURCE_LABEL["unavailable"]))


if run_it and not config.missing_required():
    # Show each agent as it finishes instead of a blank spinner. The snapshots
    # come from LangGraph's stream, so nothing here tracks progress by hand.
    #
    # snapshot is set to None before the loop rather than left to the for-loop
    # to define it: if the stream ever yields zero snapshots (an unexpected
    # provider or graph failure), referencing an undefined snapshot afterwards
    # would crash with a second, more confusing error on top of the first.
    with st.status(f"Running the crew on {ticker}", expanded=True) as running:
        shown = 0
        snapshot = None
        try:
            for snapshot in graph.stream_crew(ticker, str(start_date), str(end_date)):
                for entry in snapshot.get("conversation_log", [])[shown:]:
                    st.write(f"**{entry['agent']}** - {entry['message']}")
                    shown += 1
        except Exception as error:
            log.error("crew run failed for %s: %s", ticker, error)
            running.update(label=f"Failed to analyse {ticker}", state="error", expanded=True)
            st.error(f"Something went wrong while analysing {ticker}: {error}")
            st.stop()

        if snapshot is None:
            running.update(label=f"Failed to analyse {ticker}", state="error", expanded=True)
            st.error(f"No result was produced for {ticker}. Check output/run.log and try again.")
            st.stop()

        st.session_state["result"] = snapshot
        running.update(label=f"Finished {ticker}", state="complete", expanded=False)

result = st.session_state.get("result")

if not result:
    st.info("Enter a ticker on the left and press Run the crew.")
    st.stop()

fundamentals = result.get("fundamentals", {})
analysis = result.get("analysis", {})
research = result.get("research", {})
charts = analysis.get("charts", {})

for problem in result.get("errors", []):
    st.warning(problem)

report_tab, fundamentals_tab, price_tab, data_tab, log_tab = st.tabs(
    ["Report", "Fundamentals", "Price & market", "Data", "Agent log"])


with report_tab:
    st.markdown(result.get("report") or "No report was produced.")

    if result.get("report"):
        try:
            pdf_path = report_pdf.build_pdf(result)
            with open(pdf_path, "rb") as handle:
                st.download_button("Download the PDF", handle.read(),
                                   file_name=f"{ticker}_report.pdf",
                                   mime="application/pdf")
        except Exception as error:
            st.error(f"Could not build the PDF: {error}")


with fundamentals_tab:
    data_source_caption(fundamentals.get("data_source", "unavailable"))
    if not fundamentals.get("available"):
        st.warning(fundamentals.get("note", "No statement data available."))
    else:
        st.subheader("The numbers")
        st.dataframe(metrics_table(fundamentals.get("metrics", {}),
                                   fundamentals.get("currency")),
                     hide_index=True, use_container_width=True)

        st.subheader("Valuation against its own history")
        for name in ("pe", "pb"):
            result_for = fundamentals.get("valuation", {}).get(name)
            title = "P/E" if name == "pe" else "P/B"
            if result_for:
                st.write(f"**{title}** {result_for['current']:.1f} today "
                         f"vs {result_for['median']:.1f} median - {result_for['verdict']}")
            else:
                st.write(f"**{title}** not enough history to compare")

        st.subheader("Red flags")
        flags = fundamentals.get("red_flags", [])
        if not flags:
            st.success("No automated check was triggered.")
        for flag in flags:
            if flag["severity"] == "high":
                st.error(flag["message"])
            else:
                st.warning(flag["message"])

        for name in ("revenue_profit", "margins", "cash_vs_profit", "debt"):
            if charts.get(name):
                st.image(charts[name])

        st.caption(fundamentals.get("data_note", ""))


with price_tab:
    data_source_caption(analysis.get("data_source", "unavailable"))
    if not analysis.get("available"):
        st.warning(analysis.get("note", "No price data available."))
    else:
        st.dataframe(metrics_table(analysis.get("kpis", {})),
                     hide_index=True, use_container_width=True)
        st.write(f"**Trend** {analysis.get('trend')}")
        against_index = analysis.get("benchmark")
        if against_index:
            st.write(f"**Against {analysis.get('benchmark_symbol')}** "
                     f"{against_index['verdict']}")
        st.caption(f"Sharpe uses a risk-free rate of "
                   f"{analysis.get('risk_free_rate', 0):.1%}.")
        if charts.get("price"):
            st.image(charts["price"])

        st.subheader("News")
        data_source_caption(research.get("news_data_source", "unavailable"))
        for article in research.get("articles", []):
            st.write(f"[{article.get('published')}] {article.get('title')}")

        st.subheader("Retail chatter")
        data_source_caption(research.get("social_data_source", "unavailable"))
        st.write(research.get("social_sentiment"))


with data_tab:
    st.caption("Everything the report is built on. Every figure here was "
               "calculated in Python, not by the language model.")
    if fundamentals.get("series"):
        st.subheader("Financial statements")
        st.dataframe(pd.DataFrame(
            {name: values for name, values in fundamentals["series"].items()
             if name in ("revenue", "operating_income", "net_income",
                         "operating_cash_flow", "total_debt", "total_equity")}))
    if analysis.get("price_series", {}).get("close") is not None:
        st.subheader("Prices")
        st.line_chart(analysis["price_series"]["close"])


with log_tab:
    st.caption("What each agent did, in order. Not the model's private reasoning - "
               "just what it was asked and what it decided.")
    log_entries = result.get("conversation_log", [])

    for number, entry in enumerate(log_entries, start=1):
        agent = entry.get("agent")
        message = entry.get("message", "")
        if agent == "orchestrator_review":
            # orchestrator_review appears once at the very end when the report
            # is accepted, or in the middle - followed by the agent it sent
            # work back to - when it is not. That position, not the wording of
            # the message, is what tells the two apart reliably.
            accepted = entry is log_entries[-1]
            icon = "✅" if accepted else "\U0001f501"   # check mark, repeat
            heading = "Reviewer - accepted" if accepted else "Reviewer - sending work back"
            st.write(f"{icon} **{number}. {heading}** - {message}")
        else:
            st.write(f"**{number}. {agent}** - {message}")

    st.divider()
    if not result.get("report"):
        # No report was ever attempted - an unconfirmed ticker stops the crew
        # before report_writer runs, so there is nothing for the reviewer to
        # have accepted or sent back. Saying "accepted" here would be wrong.
        st.info("The crew stopped before writing a report - see the errors above.")
    else:
        revisions = result.get("revision_count", 0)
        cap = result.get("max_revisions", config.MAX_REVISIONS)
        if revisions == 0:
            st.success("Accepted on the first draft - no revisions needed.")
        elif revisions >= cap:
            st.warning(f"Accepted after {revisions} of {cap} revisions - the cap was reached, "
                       "so the report stands even if the reviewer would have asked for more.")
        else:
            st.success(f"Accepted after {revisions} of {cap} possible revisions.")
