"""Streamlit UI for the financial research crew.

The UI sends requests directly to the FastAPI service. Agent work stays in the
backend and LangGraph workflow.
"""

import datetime as dt
import json

import pandas as pd
import requests
import streamlit as st

from src import config, formatting, serialise

log = config.get_logger(__name__)

API_URL = config.API_URL.rstrip("/")
API_PUBLIC_URL = config.API_PUBLIC_URL.rstrip("/")
QUICK_TIMEOUT = 15
RUN_TIMEOUT = 900

st.set_page_config(
    page_title="Financial Research Agent",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Financial Research Agent")
st.caption(
    "Five agents research a company and write a financial analysis report. "
    "Informational only - not investment advice."
)


def metrics_table(values, currency=None):
    """Build the evidence table shown for calculated metrics."""
    rows = []
    for name, value in values.items():
        evidence = formatting.evidence_for(name)
        rows.append(
            {
                "Measure": formatting.label(name),
                "Value": formatting.metric(name, value, currency),
                "Period": evidence["period"],
                "Source": evidence["source"],
                "Formula": evidence["formula"],
            }
        )
    return pd.DataFrame(rows)


DATA_SOURCE_LABEL = {
    "live": "live - fetched during this run",
    "cached": "cached - reused from an earlier fetch",
    "unavailable": "unavailable - nothing came back",
}


def data_source_caption(source):
    """Show whether a section used live, cached, or unavailable data."""
    st.caption(DATA_SOURCE_LABEL.get(source, DATA_SOURCE_LABEL["unavailable"]))


def series_frame(series_by_name, wanted):
    """Rebuild API record lists as pandas Series for display."""
    columns = {}
    for name in wanted:
        records = series_by_name.get(name)
        if records:
            columns[name] = serialise.records_to_series(records)
    return pd.DataFrame(columns) if columns else None


with st.sidebar:
    st.header("Company")
    ticker = st.text_input(
        "Ticker",
        value="AAPL",
        help=(
            "Examples: AAPL, MSFT or BA. Other exchanges may need a suffix "
            "such as .L or .NS."
        ),
    )
    today = dt.date.today()
    start_date = st.date_input(
        "From",
        value=today - dt.timedelta(days=365 * 3),
    )
    end_date = st.date_input("To", value=today)
    run_it = st.button("Run the crew", type="primary", use_container_width=True)

    st.divider()
    st.subheader("Backend")
    st.caption(f"API: {config.API_URL}")

    try:
        response = requests.get(f"{API_URL}/health", timeout=QUICK_TIMEOUT)
        response.raise_for_status()
        service = response.json()

        if service.get("missing_config"):
            st.error(
                "The API is up but not configured: "
                + ", ".join(service["missing_config"])
            )
        else:
            st.success(f"Connected - {service.get('model')}")

        st.subheader("Data sources")
        for name, switched_on in (service.get("sources") or {}).items():
            st.write(("ON - " if switched_on else "off - ") + name)
        api_reachable = True
    except (requests.RequestException, ValueError) as error:
        st.error(f"Could not reach the API: {error}")
        st.caption("Start it with: uvicorn api:app --port 8000")
        api_reachable = False


if run_it:
    st.session_state.pop("result", None)

    if not api_reachable:
        st.error("The analysis cannot start until the API is reachable.")
        st.stop()

    payload = {
        "ticker": ticker.strip().upper(),
        "start_date": str(start_date),
        "end_date": str(end_date),
    }

    with st.status(f"Running the crew on {ticker}", expanded=True) as running:
        result = None
        try:
            with requests.post(
                f"{API_URL}/analyse/stream",
                json=payload,
                stream=True,
                timeout=RUN_TIMEOUT,
            ) as response:
                response.raise_for_status()

                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue

                    event = json.loads(line)
                    event_type = event.get("event")

                    if event_type == "progress":
                        st.write(
                            f"**{event.get('agent')}** - {event.get('message')}"
                        )
                    elif event_type == "result":
                        result = event.get("result")
                    elif event_type == "error":
                        raise RuntimeError(event.get("detail", "The analysis failed"))

        except (requests.RequestException, json.JSONDecodeError, RuntimeError) as error:
            log.error("run failed for %s: %s", ticker, error)
            running.update(
                label=f"Failed to analyse {ticker}",
                state="error",
                expanded=True,
            )
            st.error(str(error))
            st.stop()

        if result is None:
            running.update(
                label=f"Failed to analyse {ticker}",
                state="error",
                expanded=True,
            )
            st.error(f"No result was produced for {ticker}.")
            st.stop()

        st.session_state["result"] = result
        running.update(
            label=f"Finished {ticker}",
            state="complete",
            expanded=False,
        )


result = st.session_state.get("result")

if not result:
    st.info("Enter a ticker on the left and press Run the crew.")
    st.stop()

result_ticker = result.get("ticker") or ticker
fundamentals = result.get("fundamentals") or {}
analysis = result.get("analysis") or {}
research = result.get("research") or {}
charts = analysis.get("charts") or {}

st.caption(f"Showing the latest completed analysis for {result_ticker}.")

for problem in result.get("errors") or []:
    st.warning(problem)

report_tab, fundamentals_tab, price_tab, data_tab, log_tab = st.tabs(
    ["Report", "Fundamentals", "Price & market", "Data", "Agent log"]
)


with report_tab:
    st.markdown(result.get("report") or "No report was produced.")

    pdf_url = result.get("pdf_url")
    if pdf_url:
        try:
            response = requests.get(
                f"{API_URL}{pdf_url}",
                timeout=QUICK_TIMEOUT,
            )
            response.raise_for_status()
            st.download_button(
                "Download the PDF",
                response.content,
                file_name=f"{result_ticker}_report.pdf",
                mime="application/pdf",
            )
        except requests.RequestException as error:
            st.error(f"Could not fetch the PDF: {error}")


with fundamentals_tab:
    data_source_caption(fundamentals.get("data_source", "unavailable"))

    if not fundamentals.get("available"):
        st.warning(fundamentals.get("note", "No statement data available."))
    else:
        st.subheader("Financial metrics")
        st.dataframe(
            metrics_table(
                fundamentals.get("metrics") or {},
                fundamentals.get("currency"),
            ),
            hide_index=True,
            use_container_width=True,
        )

        st.subheader("Valuation against its own history")
        for name in ("pe", "pb"):
            value = (fundamentals.get("valuation") or {}).get(name)
            title = "P/E" if name == "pe" else "P/B"
            if value:
                st.write(
                    f"**{title}** {value['current']:.1f} today vs "
                    f"{value['median']:.1f} median - {value['verdict']}"
                )
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
                st.image(f"{API_PUBLIC_URL}{charts[name]}")


with price_tab:
    data_source_caption(analysis.get("data_source", "unavailable"))

    if not analysis.get("available"):
        st.warning(analysis.get("note", "No price data available."))
    else:
        st.dataframe(
            metrics_table(analysis.get("kpis") or {}),
            hide_index=True,
            use_container_width=True,
        )
        st.write(f"**Trend:** {analysis.get('trend')}")

        benchmark = analysis.get("benchmark")
        if benchmark:
            st.write(
                f"**Against {analysis.get('benchmark_symbol')}:** "
                f"{benchmark['verdict']}"
            )

        if charts.get("price"):
            st.image(f"{API_PUBLIC_URL}{charts['price']}")

    st.subheader("News")
    data_source_caption(research.get("news_data_source", "unavailable"))
    for article in research.get("articles") or []:
        st.write(f"[{article.get('published')}] {article.get('title')}")

    st.subheader("Retail chatter")
    data_source_caption(research.get("social_data_source", "unavailable"))
    st.write(research.get("social_sentiment") or "No social sentiment available.")


with data_tab:
    st.caption(
        "The report uses calculated Python values and fetched source data. "
        "The language model does not calculate the financial metrics."
    )

    statements = series_frame(
        fundamentals.get("series") or {},
        (
            "revenue",
            "operating_income",
            "net_income",
            "operating_cash_flow",
            "total_debt",
            "total_equity",
        ),
    )
    if statements is not None:
        st.subheader("Financial statements")
        st.dataframe(statements)

    prices = (analysis.get("price_series") or {}).get("close")
    if prices:
        st.subheader("Prices")
        st.line_chart(serialise.records_to_series(prices))


with log_tab:
    st.caption("What each agent did during the workflow.")

    log_entries = result.get("conversation_log") or []
    for number, entry in enumerate(log_entries, start=1):
        agent = entry.get("agent")
        message = entry.get("message", "")
        st.write(f"**{number}. {agent}** - {message}")

    if result.get("report"):
        revisions = result.get("revision_count", 0)
        st.caption(f"Revisions used: {revisions}")
