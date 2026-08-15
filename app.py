"""The Streamlit app: type a ticker, get a report.

Five tabs so the reader can go from the written report down to the raw numbers
that produced it.
"""

import datetime as dt

import pandas as pd
import streamlit as st

from src import config, formatting, graph, report_pdf

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
    """A two column table of metric name and value."""
    rows = []
    for name, value in values.items():
        rows.append({"Measure": formatting.label(name),
                     "Value": formatting.metric(name, value, currency)})
    return pd.DataFrame(rows)


if run_it:
    if config.missing_required():
        st.stop()
    with st.spinner(f"Running the crew on {ticker}. This takes a minute or two."):
        st.session_state["result"] = graph.run_crew(
            ticker, str(start_date), str(end_date))

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
        for article in research.get("articles", []):
            st.write(f"[{article.get('published')}] {article.get('title')}")
        st.write(f"**Retail chatter** {research.get('social_sentiment')}")


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
    st.caption("What each agent did, in order.")
    for number, entry in enumerate(result.get("conversation_log", []), start=1):
        st.write(f"**{number}. {entry.get('agent')}** - {entry.get('message')}")
    st.write(f"Revisions used: {result.get('revision_count', 0)} "
             f"of {result.get('max_revisions', config.MAX_REVISIONS)}")
