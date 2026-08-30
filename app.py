"""The Streamlit app: type a ticker, get a report.

This is the front end and nothing else. It runs no agents, calls no model and
fetches no market data - it asks the FastAPI service (api.py) for all of that
over HTTP. The only project modules it imports are the API client, the config
that tells it where the API is, and the shared formatting helpers.

Run the API first, then this:

    uvicorn api:app --port 8000
    streamlit run app.py
"""

import datetime as dt

import pandas as pd
import streamlit as st

from src import api_client, config, formatting, serialise

log = config.get_logger(__name__)

st.set_page_config(page_title="Financial Research Agent", layout="wide",
                   initial_sidebar_state="expanded")

st.title("Financial Research Agent")
st.caption("Five agents research a company and write a fundamental analysis report. "
           "Informational only - not investment advice.")


# --- Sidebar: what to analyse, and what the API says is switched on ---------
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
    st.subheader("Backend")
    st.caption(f"API: {config.API_URL}")

    # Asked of the API rather than read from local config: the app is not the
    # thing holding the keys any more, so it cannot answer this itself.
    try:
        service = api_client.health()
        if service.get("missing_config"):
            st.error("The API is up but not configured: "
                     + ", ".join(service["missing_config"]))
        else:
            st.success(f"Connected - {service.get('model')}")
        st.subheader("Data sources")
        for name, switched_on in (service.get("sources") or {}).items():
            st.write(("ON - " if switched_on else "off - ") + name)
        api_reachable = True
    except api_client.ApiError as error:
        st.error(str(error))
        st.caption("Start it with:  uvicorn api:app --port 8000")
        api_reachable = False


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


def series_frame(series_by_name, wanted):
    """The API sends each series as records; rebuild the ones we display."""
    columns = {}
    for name in wanted:
        records = series_by_name.get(name)
        if records:
            columns[name] = serialise.records_to_series(records)
    return pd.DataFrame(columns) if columns else None


if run_it and api_reachable:
    # The API streams one line per agent as it finishes, so this shows the crew
    # working rather than a blank spinner. result stays None until the final
    # line arrives: a stream that ends early must not look like a success.
    with st.status(f"Running the crew on {ticker}", expanded=True) as running:
        result = None
        try:
            for event in api_client.stream_analysis(ticker, str(start_date), str(end_date)):
                if event.get("event") == "progress":
                    st.write(f"**{event.get('agent')}** - {event.get('message')}")
                elif event.get("event") == "result":
                    result = event.get("result")
        except api_client.ApiError as error:
            log.error("run failed for %s: %s", ticker, error)
            running.update(label=f"Failed to analyse {ticker}", state="error", expanded=True)
            st.error(str(error))
            st.stop()

        if result is None:
            running.update(label=f"Failed to analyse {ticker}", state="error", expanded=True)
            st.error(f"No result was produced for {ticker}. Check the API log and try again.")
            st.stop()

        st.session_state["result"] = result
        running.update(label=f"Finished {ticker}", state="complete", expanded=False)

result = st.session_state.get("result")

if not result:
    st.info("Enter a ticker on the left and press Run the crew.")
    st.stop()

fundamentals = result.get("fundamentals") or {}
analysis = result.get("analysis") or {}
research = result.get("research") or {}
charts = analysis.get("charts") or {}

for problem in result.get("errors") or []:
    st.warning(problem)

report_tab, fundamentals_tab, price_tab, data_tab, log_tab = st.tabs(
    ["Report", "Fundamentals", "Price & market", "Data", "Agent log"])


with report_tab:
    st.markdown(result.get("report") or "No report was produced.")

    if result.get("pdf_url"):
        try:
            st.download_button("Download the PDF", api_client.fetch_pdf(result["pdf_url"]),
                               file_name=f"{ticker}_report.pdf",
                               mime="application/pdf")
        except api_client.ApiError as error:
            st.error(str(error))


with fundamentals_tab:
    data_source_caption(fundamentals.get("data_source", "unavailable"))
    if not fundamentals.get("available"):
        st.warning(fundamentals.get("note", "No statement data available."))
    else:
        st.subheader("The numbers")
        st.dataframe(metrics_table(fundamentals.get("metrics") or {},
                                   fundamentals.get("currency")),
                     hide_index=True, use_container_width=True)

        st.subheader("Valuation against its own history")
        for name in ("pe", "pb"):
            result_for = (fundamentals.get("valuation") or {}).get(name)
            title = "P/E" if name == "pe" else "P/B"
            if result_for:
                st.write(f"**{title}** {result_for['current']:.1f} today "
                         f"vs {result_for['median']:.1f} median - {result_for['verdict']}")
            else:
                st.write(f"**{title}** not enough history to compare")

        st.subheader("Red flags")
        flags = fundamentals.get("red_flags") or []
        if not flags:
            st.success("No automated check was triggered.")
        for flag in flags:
            if flag["severity"] == "high":
                st.error(flag["message"])
            else:
                st.warning(flag["message"])

        for name in ("revenue_profit", "margins", "cash_vs_profit", "debt"):
            if charts.get(name):
                st.image(api_client.chart_url(charts[name]))

        st.caption(fundamentals.get("data_note", ""))


with price_tab:
    data_source_caption(analysis.get("data_source", "unavailable"))
    if not analysis.get("available"):
        st.warning(analysis.get("note", "No price data available."))
    else:
        st.dataframe(metrics_table(analysis.get("kpis") or {}),
                     hide_index=True, use_container_width=True)
        st.write(f"**Trend** {analysis.get('trend')}")
        against_index = analysis.get("benchmark")
        if against_index:
            st.write(f"**Against {analysis.get('benchmark_symbol')}** "
                     f"{against_index['verdict']}")
        st.caption(f"Sharpe uses a risk-free rate of "
                   f"{analysis.get('risk_free_rate', 0):.1%}.")
        if charts.get("price"):
            st.image(api_client.chart_url(charts["price"]))

        st.subheader("News")
        data_source_caption(research.get("news_data_source", "unavailable"))
        for article in research.get("articles") or []:
            st.write(f"[{article.get('published')}] {article.get('title')}")

        st.subheader("Retail chatter")
        data_source_caption(research.get("social_data_source", "unavailable"))
        st.write(research.get("social_sentiment"))


with data_tab:
    st.caption("Everything the report is built on. Every figure here was "
               "calculated in Python, not by the language model.")

    statements = series_frame(fundamentals.get("series") or {},
                              ("revenue", "operating_income", "net_income",
                               "operating_cash_flow", "total_debt", "total_equity"))
    if statements is not None:
        st.subheader("Financial statements")
        st.dataframe(statements)

    prices = (analysis.get("price_series") or {}).get("close")
    if prices:
        st.subheader("Prices")
        st.line_chart(serialise.records_to_series(prices))


with log_tab:
    st.caption("What each agent did, in order. Not the model's private reasoning - "
               "just what it was asked and what it decided.")
    log_entries = result.get("conversation_log") or []

    for number, entry in enumerate(log_entries, start=1):
        agent = entry.get("agent")
        message = entry.get("message", "")
        if agent == "orchestrator_review":
            # orchestrator_review appears once at the very end when the report
            # is accepted, or in the middle - followed by the agent it sent
            # work back to - when it is not. That position, not the wording of
            # the message, is what tells the two apart reliably.
            accepted = number == len(log_entries)
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
