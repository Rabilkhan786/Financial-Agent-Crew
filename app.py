"""Streamlit UI for the financial analysis crew."""

import datetime as dt
import json

import pandas as pd
import requests
import streamlit as st

from src.components import config
from src.components.logging import get_logger
from src.utils import formatting, serialization

log = get_logger(__name__)

API_URL = config.API_URL
API_PUBLIC_URL = config.API_PUBLIC_URL
QUICK_TIMEOUT = 15
RUN_TIMEOUT = 900

st.set_page_config(page_title="Financial Research Agent", layout="wide")
st.title("Financial Research Agent")
st.caption("Multi-agent financial analysis for educational use only.")


def metrics_table(values, currency=None):
    """Build a readable table for calculated metrics."""
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


def public_url(path):
    """Convert an API path into a browser-visible URL."""
    return f"{API_PUBLIC_URL}{path}"


with st.sidebar:
    st.header("Company")
    ticker = st.text_input("Ticker", value="AAPL").strip().upper()

    today = dt.date.today()
    start_date = st.date_input(
        "From",
        value=today - dt.timedelta(days=365 * 3),
    )
    end_date = st.date_input("To", value=today)
    run_analysis = st.button(
        "Run analysis",
        type="primary",
        use_container_width=True,
    )

    st.divider()
    st.subheader("Backend")

    try:
        health = requests.get(
            f"{API_URL}/health",
            timeout=QUICK_TIMEOUT,
        )
        health.raise_for_status()
        service = health.json()
        api_ready = not service.get("missing_config")

        if api_ready:
            st.success(f"Connected - {service.get('model')}")
        else:
            st.error(
                "Missing configuration: "
                + ", ".join(service.get("missing_config") or [])
            )
    except (requests.RequestException, ValueError) as error:
        st.error(f"API unavailable: {error}")
        api_ready = False


if run_analysis:
    st.session_state.pop("result", None)

    if not api_ready:
        st.error("Start and configure the FastAPI backend first.")
        st.stop()

    payload = {
        "ticker": ticker,
        "start_date": str(start_date),
        "end_date": str(end_date),
    }

    result = None
    with st.status(f"Analyzing {ticker}", expanded=True) as status:
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
                    if event.get("event") == "progress":
                        st.write(
                            f"**{event.get('agent')}** - "
                            f"{event.get('message')}"
                        )
                    elif event.get("event") == "error":
                        raise RuntimeError(event.get("detail", "Analysis failed"))
                    elif event.get("event") == "result":
                        result = event.get("result")
        except (requests.RequestException, ValueError, RuntimeError) as error:
            log.error("Analysis failed for %s: %s", ticker, error)
            status.update(label="Analysis failed", state="error")
            st.error(str(error))
            st.stop()

        if result is None:
            status.update(label="No result produced", state="error")
            st.error("The backend did not return a result.")
            st.stop()

        st.session_state["result"] = result
        status.update(label=f"Finished {ticker}", state="complete")


result = st.session_state.get("result")
if not result:
    st.info("Enter a ticker and run the analysis.")
    st.stop()

result_ticker = result.get("ticker") or ticker
fundamentals = result.get("fundamentals") or {}
analysis = result.get("analysis") or {}
research = result.get("research") or {}
charts = analysis.get("charts") or {}

report_tab, fundamentals_tab, price_tab, data_tab, log_tab = st.tabs(
    ["Report", "Fundamentals", "Price", "Data", "Agent log"]
)

with report_tab:
    st.markdown(result.get("report") or "No report was generated.")

    if result.get("pdf_url"):
        try:
            pdf = requests.get(
                f"{API_URL}{result['pdf_url']}",
                timeout=QUICK_TIMEOUT,
            )
            pdf.raise_for_status()
            st.download_button(
                "Download PDF",
                data=pdf.content,
                file_name=f"{result_ticker}_report.pdf",
                mime="application/pdf",
            )
        except requests.RequestException as error:
            st.warning(f"PDF unavailable: {error}")

with fundamentals_tab:
    if not fundamentals.get("available"):
        st.warning(fundamentals.get("note", "No fundamental data available."))
    else:
        st.dataframe(
            metrics_table(
                fundamentals.get("metrics") or {},
                fundamentals.get("currency"),
            ),
            hide_index=True,
            use_container_width=True,
        )

        st.subheader("Valuation")
        for name in ("pe", "pb"):
            value = (fundamentals.get("valuation") or {}).get(name)
            label = "P/E" if name == "pe" else "P/B"
            if value:
                st.write(
                    f"**{label}:** {value['current']:.1f} current vs "
                    f"{value['median']:.1f} median - {value['verdict']}"
                )
            else:
                st.write(f"**{label}:** unavailable")

        st.subheader("Red flags")
        flags = fundamentals.get("red_flags") or []
        if not flags:
            st.success("No automated red flags were triggered.")
        for flag in flags:
            st.warning(flag.get("message"))

        for chart_name in (
            "revenue_profit",
            "margins",
            "cash_vs_profit",
            "debt",
        ):
            if charts.get(chart_name):
                st.image(public_url(charts[chart_name]))

with price_tab:
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
                f"{benchmark.get('verdict')}"
            )

        if charts.get("price"):
            st.image(public_url(charts["price"]))

    st.subheader("Recent news")
    for article in research.get("articles") or []:
        st.write(
            f"[{article.get('published') or 'undated'}] "
            f"{article.get('title')}"
        )

    st.subheader("Retail sentiment")
    st.write(research.get("social_sentiment") or "unavailable")

with data_tab:
    st.caption("Calculated values come from Python, not from the LLM.")

    statement_series = fundamentals.get("series") or {}
    statement_columns = {}
    for name in (
        "revenue",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "total_debt",
        "total_equity",
    ):
        records = statement_series.get(name)
        if records:
            statement_columns[name] = serialization.records_to_series(records)

    if statement_columns:
        st.subheader("Financial statements")
        st.dataframe(pd.DataFrame(statement_columns))

    prices = (analysis.get("price_series") or {}).get("close")
    if prices:
        st.subheader("Closing price")
        st.line_chart(serialization.records_to_series(prices))

with log_tab:
    for number, entry in enumerate(
        result.get("conversation_log") or [],
        start=1,
    ):
        st.write(
            f"**{number}. {entry.get('agent')}** - {entry.get('message')}"
        )
