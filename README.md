# Financial Research Agent Crew

A simple multi-agent financial analysis project built with LangGraph, FastAPI, Streamlit, pandas, and Yahoo Finance.

The user enters a stock ticker and date range. The application collects company data, calculates financial metrics in Python, asks specialized agents to explain the results, and produces a final report with charts and a PDF.

> Educational project only. This is not investment advice.

## How the app works

```text
User
  ↓
Streamlit UI
  ↓
FastAPI
  ↓
LangGraph
  ↓
Orchestrator
  ↓
Market Researcher
  ↓
Fundamentals Analyst
  ↓
Data Analyst
  ↓
Report Writer
  ↓
Orchestrator Review
  ├── accept → END
  ├── market issue → Market Researcher → ... → Review
  └── fundamentals issue → Fundamentals Analyst → ... → Review
```

Python performs the financial calculations. The LLM is used to explain the calculated values, summarize market context, write the report, and review the final output.

## Project structure

```text
Financial-Agent-Crew/
├── app.py
├── api.py
├── config.yaml
├── .env.example
├── src/
│   ├── components/
│   │   ├── config.py
│   │   └── logging.py
│   ├── core/
│   │   ├── graph.py
│   │   ├── state.py
│   │   └── llm.py
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── market_researcher.py
│   │   ├── fundamentals_analyst.py
│   │   ├── data_analyst.py
│   │   └── report_writer.py
│   ├── tools/
│   │   ├── market_data.py
│   │   ├── statements.py
│   │   ├── news.py
│   │   ├── social.py
│   │   ├── ratios.py
│   │   └── kpi.py
│   └── utils/
│       ├── formatting.py
│       ├── charts.py
│       ├── serialization.py
│       └── report_pdf.py
├── tests/
│   ├── test_api.py
│   ├── test_graph.py
│   ├── test_orchestrator.py
│   ├── test_kpi.py
│   └── test_ratios.py
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Agent responsibilities

### Orchestrator

Validates the ticker, starts the workflow, reviews the final report, and controls the revision loop.

### Market Researcher

Fetches Yahoo Finance news and StockTwits posts, then summarizes recent company context and retail sentiment.

### Fundamentals Analyst

Fetches annual financial statements and uses deterministic Python functions to calculate growth, margins, cash flow, debt, returns, valuation comparisons, and red flags.

### Data Analyst

Fetches price history and a benchmark index, then calculates return, volatility, maximum drawdown, Sharpe ratio, moving averages, and benchmark performance. It also creates the charts.

### Report Writer

Combines the findings from the other agents into one structured report. It does not calculate new financial values.

## Why LangGraph

The workflow is not only a straight chain. After the report is written, the orchestrator reviews it. If a market-context issue is found, LangGraph routes the workflow back to the Market Researcher. If a fundamentals issue is found, it routes back to the Fundamentals Analyst. The revision count is limited in `config.yaml` so the workflow cannot loop forever.

## Configuration

Normal project settings live in `config.yaml`.

```yaml
llm:
  model: "openai/gpt-oss-120b"
  temperature: 0.2
  timeout: 180
  max_tokens: 4096

workflow:
  max_revisions: 1
  recursion_limit: 20
```

Secrets stay in `.env`.

```text
GROQ_API_KEY=your_key_here
API_URL=http://localhost:8000
API_PUBLIC_URL=http://localhost:8000
```

## Run locally

Create an environment and install the dependencies:

```bash
uv venv
uv pip install -r requirements.txt
```

Start FastAPI:

```bash
uvicorn api:app --reload --port 8000
```

Start Streamlit in another terminal:

```bash
streamlit run app.py
```

Open `http://localhost:8501`.

## Run with Docker

```bash
docker compose up --build
```

- Streamlit: `http://localhost:8501`
- FastAPI: `http://localhost:8000`

## Tests

```bash
pytest -q
```

The tests focus on API behavior, LangGraph routing, the review loop, financial ratios, and price KPIs.
