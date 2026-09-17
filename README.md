# Financial Research Agent Crew

A multi-agent financial research project built with LangGraph, FastAPI, and Streamlit.

The application takes a stock ticker and date range, collects public market data,
calculates financial metrics in Python, gathers recent market context, and produces
a structured company analysis report.

The project is designed so that **financial calculations are deterministic**. The
LLM explains already-calculated values; it does not calculate the ratios itself.

> This project is for informational and educational use. It is not investment advice.

## What problem does it solve?

Researching a company usually means checking several different things:

- financial statements,
- profitability and growth,
- debt and cash flow,
- share-price performance,
- benchmark performance,
- recent news,
- retail-market discussion.

This project combines those steps into one workflow and keeps a record of what each
agent did.

## Main workflow

```text
User enters ticker + date range
            |
            v
       Streamlit app
            |
            v
        FastAPI API
            |
            v
      LangGraph workflow
            |
            v
       Orchestrator
     validates ticker
            |
            v
    Market Researcher
   news + social context
            |
            v
  Fundamentals Analyst
 statements + ratios + flags
            |
            v
       Data Analyst
 price KPIs + benchmark + charts
            |
            v
       Report Writer
 combines existing findings
            |
            v
    Orchestrator Review
 deterministic checks + review
            |
       accept / revise
            |
            v
   Report + charts + PDF
```

The reviewer can send work back to the fundamentals analyst or market researcher.
The revision count is capped so the graph cannot loop forever.

## Agent responsibilities

### Orchestrator

Validates the ticker, records the company name, starts the workflow, and reviews the
finished report.

Before using an LLM for contradiction review, it performs deterministic checks:

- required red flags must be represented in the report,
- report numbers must trace back to calculated values or fetched article text,
- revision count must stay within the configured limit.

### Market researcher

Collects recent news and StockTwits posts. Finnhub and Alpha Vantage are optional;
Yahoo Finance remains the default news fallback.

When there are too few social posts, the result is `insufficient data` instead of
trying to infer sentiment from a tiny sample.

### Fundamentals analyst

Fetches annual statements and calculates financial metrics through
`src/tools/ratios.py`.

Examples include:

- revenue growth and revenue CAGR,
- operating and net margin,
- cash conversion,
- free cash flow,
- debt to equity,
- interest coverage,
- ROE and ROCE,
- P/E and P/B compared with the company's own history.

It also produces deterministic red flags for conditions such as weak cash conversion,
high leverage, margin erosion, negative equity, or falling revenue.

### Data analyst

Fetches historical prices, selects an appropriate benchmark, calculates price KPIs,
and generates charts.

Examples include:

- total and annualised return,
- volatility,
- maximum drawdown,
- Sharpe ratio,
- 50-day and 200-day moving averages,
- return versus the benchmark index.

### Report writer

Combines the findings already stored in the shared state. It is instructed to use
only supplied evidence and calculated values.

The final section summarises positive evidence, risks, and what new information could
change the assessment. It does not tell the user to buy, sell, hold, wait, or avoid a
security.

## Why LangGraph?

A simple chain would work if every step only moved forward. This project needs one
controlled loop: after the report is written, the reviewer may send work back to an
earlier agent and then review the new report again.

That conditional revision edge is the main reason LangGraph is useful here.

## Deterministic finance logic

The LLM is not used for calculations.

`src/tools/ratios.py` contains statement-based finance calculations and red-flag
rules. `src/tools/kpi.py` contains price and risk calculations. Both are plain
pandas/numpy code and can be tested independently.

This separation makes the project easier to explain:

```text
external data -> Python calculation -> structured facts -> LLM explanation
```

If a required value is missing or unusable, the calculation returns `None` and the
report describes the metric as unavailable rather than inventing a value.

## Number provenance check

`src/tools/sourcing.py` checks numbers written in the report against values the
application is allowed to use.

Allowed numbers can come from:

- calculated financial metrics,
- calculated price KPIs,
- historical statement series,
- benchmark comparisons,
- deterministic social/news sentiment counts,
- numbers present in fetched article titles or summaries.

If the report contains an unsupported number, the reviewer can send the report back
for correction.

## Cache behaviour

External data is cached under `.cache/`.

`cache.cached()` returns both the value and its source:

- `live` — fetched successfully during the current request,
- `cached` — reused from a fresh cache entry or stale fallback,
- `unavailable` — assigned by the caller when no usable data could be obtained.

If an external provider fails and an older cached value exists, the application can
reuse that stale value instead of failing the whole analysis.

The Streamlit UI displays the source status so the user can distinguish live data
from reused data.

## Project structure

```text
Financial-Agent-Crew/
├── api.py                    # FastAPI endpoints
├── app.py                    # Streamlit UI
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── evals/
│   └── run_eval.py           # multi-company evaluation script
├── src/
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── market_researcher.py
│   │   ├── fundamentals_analyst.py
│   │   ├── data_analyst.py
│   │   └── report_writer.py
│   ├── tools/
│   │   ├── statements.py
│   │   ├── ratios.py
│   │   ├── market_data.py
│   │   ├── kpi.py
│   │   ├── news.py
│   │   ├── social.py
│   │   └── sourcing.py
│   ├── api_client.py
│   ├── cache.py
│   ├── charts.py
│   ├── config.py
│   ├── formatting.py
│   ├── graph.py
│   ├── llm.py
│   ├── report_pdf.py
│   ├── serialise.py
│   └── state.py
├── tests/
└── output/
```

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Rabilkhan786/Financial-Agent-Crew.git
cd Financial-Agent-Crew
```

### 2. Create a virtual environment

Using `uv`:

```bash
uv venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
uv pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and add your Groq key:

```env
GROQ_API_KEY=your_key_here
```

Optional integrations:

```env
FINNHUB_API_KEY=
ALPHAVANTAGE_API_KEY=
```

Yahoo Finance and StockTwits do not require keys in this project.

## Run locally

Start the API:

```bash
uvicorn api:app --reload --port 8000
```

In another terminal, start Streamlit:

```bash
streamlit run app.py
```

Then open the Streamlit address shown in the terminal.

FastAPI documentation is available at:

```text
http://localhost:8000/docs
```

## Run with Docker

```bash
docker compose up --build
```

The default compose configuration exposes:

```text
API:        http://localhost:8000
Streamlit:  http://localhost:8501
```

The API and Streamlit app run in separate containers so each process has one clear
responsibility.

## API endpoints

### Health

```text
GET /health
```

Returns model configuration and enabled data sources.

### Run an analysis

```text
POST /analyse
```

Example request:

```json
{
  "ticker": "AAPL",
  "start_date": "2023-01-01",
  "end_date": "2026-01-01"
}
```

The API validates the date format and rejects a start date that is after the end date.

### Stream analysis progress

```text
POST /analyse/stream
```

Returns newline-delimited JSON events for agent progress and the final result.

### Generated files

```text
GET /charts/{filename}
GET /report/{ticker}/pdf
```

The chart endpoint only serves generated PNG files from the output directory.

## Testing

Fast tests are offline:

```bash
pytest tests/ -q
```

Live integration tests require network access and a configured model key:

```bash
pytest tests/ -q --live
```

The test suite covers the important deterministic parts of the project, including:

- finance ratios and red flags,
- price KPIs and benchmark logic,
- report-number provenance,
- graph routing and revision limits,
- JSON serialisation,
- API validation,
- cache behaviour,
- API-client URL handling.

## Evaluation

The repository also contains a multi-company evaluation script:

```bash
python -m evals.run_eval
```

It checks whether generated reports contain blank values, unsupported numbers, or
missing required sections. Provider failures are classified separately from report
quality failures so an unavailable external service is not automatically treated as
a logic bug.

## Important design decisions

1. **Python calculates; the model explains.** Financial arithmetic and validation stay
   deterministic and testable.
2. **Missing data stays missing.** The project does not estimate unavailable statement
   values just to complete a report.
3. **The review loop is bounded.** `MAX_REVISIONS` prevents agents from revising
   forever, with LangGraph's recursion limit as an additional guard.
4. **External integrations degrade gracefully.** Optional providers can fail without
   necessarily stopping the complete run.
5. **The API is the execution boundary.** Streamlit does not run agents directly; it
   communicates with FastAPI through `src/api_client.py`.

## Current limitations

- The project depends heavily on Yahoo Finance data quality and field availability.
- Some yfinance calls do not expose a reliable per-request timeout.
- Optional news providers have their own free-tier limits and exchange restrictions.
- Model-provider token/rate limits can prevent an interpretation or report from being
  generated even when the deterministic calculations completed successfully.
- The disk cache uses pickle because cached values include pandas objects. The cache
  must therefore remain application-controlled and should not load files supplied by
  untrusted users.

## Tech stack

- Python
- LangGraph / LangChain
- Groq
- FastAPI
- Streamlit
- pandas / NumPy
- yfinance
- Matplotlib
- fpdf2
- pytest
- Docker
