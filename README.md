# Financial Research Agent Crew

A simple multi-agent financial analysis project built with LangGraph, FastAPI, Streamlit, pandas, and NumPy.

The user enters a stock ticker and date range. The application collects market data, calculates financial metrics in Python, gathers recent market context, and produces a structured company analysis report.

> Educational project only. It is not investment advice.

## Problem

Company research usually requires checking several things separately:

- financial statements,
- profitability and growth,
- debt and cash flow,
- stock-price performance,
- benchmark performance,
- recent news,
- retail-market discussion.

This project combines those steps into one workflow.

## Simple architecture

```text
User
  |
  v
Streamlit UI
  |
  v
FastAPI
  |
  v
LangGraph
  |
  v
Orchestrator
  |
  v
Market Researcher
  |
  v
Fundamentals Analyst
  |
  v
Data Analyst
  |
  v
Report Writer
  |
  v
Orchestrator Review
  |
  v
Final report + charts + PDF
```

The Streamlit app calls the FastAPI endpoints directly with `requests`. FastAPI starts the LangGraph workflow and returns progress and results to the UI.

## Agents

The project has five main agent modules.

### 1. Orchestrator

- validates the ticker,
- starts the workflow,
- reviews the final report,
- sends work back for revision when required.

### 2. Market Researcher

- fetches recent news,
- fetches retail-market discussion,
- summarizes recent company context,
- checks that model-written numbers come from fetched sources.

### 3. Fundamentals Analyst

- fetches financial statements,
- calculates financial ratios,
- detects rule-based financial red flags,
- asks the LLM to explain already-calculated results.

### 4. Data Analyst

- fetches historical prices,
- calculates return and risk metrics,
- compares the stock with a benchmark,
- creates charts.

### 5. Report Writer

- combines the completed findings,
- writes the final structured report,
- uses only supplied evidence and calculated values.

The Orchestrator also has a review step. That review is part of the same orchestrator module, not a separate sixth agent.

## LangGraph flow

```text
START
  |
  v
Orchestrator
  |
  |-- invalid ticker --> END
  |
  v
Market Researcher
  |
  v
Fundamentals Analyst
  |
  v
Data Analyst
  |
  v
Report Writer
  |
  v
Orchestrator Review
  |
  |-- accept --> END
  |
  |-- research issue --> Market Researcher
  |
  `-- fundamentals issue --> Fundamentals Analyst
```

LangGraph is useful here because the workflow needs shared state, conditional routing, and a controlled revision loop.

## Main tool modules

The `src/tools/` folder contains the main data and calculation helpers:

- `market_data.py` - company profile and market data,
- `news.py` - recent news,
- `social.py` - retail-market discussion,
- `statements.py` - financial statements,
- `ratios.py` - financial ratios and red flags,
- `kpi.py` - stock-price and risk metrics,
- `sourcing.py` - checks number provenance in model output.

## Important design decision

Financial calculations are not done by the LLM.

```text
external data
    |
    v
Python calculation
    |
    v
structured facts
    |
    v
LLM explanation
```

`ratios.py` and `kpi.py` use normal Python, pandas, and NumPy calculations. The LLM explains the results instead of inventing or calculating the financial numbers itself.

This makes the important calculations deterministic and testable.

## Project structure

```text
Financial-Agent-Crew/
|-- api.py                 # FastAPI backend
|-- app.py                 # Streamlit UI + direct API calls
|-- Dockerfile
|-- docker-compose.yml
|-- requirements.txt
|-- evals/
|   `-- run_eval.py
|-- src/
|   |-- agents/
|   |   |-- orchestrator.py
|   |   |-- market_researcher.py
|   |   |-- fundamentals_analyst.py
|   |   |-- data_analyst.py
|   |   `-- report_writer.py
|   |-- tools/
|   |   |-- market_data.py
|   |   |-- news.py
|   |   |-- social.py
|   |   |-- statements.py
|   |   |-- ratios.py
|   |   |-- kpi.py
|   |   `-- sourcing.py
|   |-- graph.py
|   |-- state.py
|   |-- llm.py
|   |-- config.py
|   |-- charts.py
|   |-- formatting.py
|   |-- serialise.py
|   `-- report_pdf.py
|-- tests/
`-- output/
```

## Run locally

### 1. Create an environment

```bash
uv venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

### 2. Install dependencies

```bash
uv pip install -r requirements.txt
```

### 3. Configure environment variables

Create `.env` from `.env.example` and add the required model key:

```env
GROQ_API_KEY=your_key_here
```

Optional providers:

```env
FINNHUB_API_KEY=
ALPHAVANTAGE_API_KEY=
```

### 4. Start FastAPI

```bash
uvicorn api:app --reload --port 8000
```

### 5. Start Streamlit

In another terminal:

```bash
streamlit run app.py
```

FastAPI docs:

```text
http://localhost:8000/docs
```

Streamlit:

```text
http://localhost:8501
```

## Docker Compose

To run the FastAPI and Streamlit services together:

```bash
docker compose up --build
```

Docker Compose starts two containers:

```text
FastAPI     -> localhost:8000
Streamlit   -> localhost:8501
```

Inside Docker, Streamlit reaches FastAPI using the service address `http://api:8000`.

## API endpoints

### Health check

```text
GET /health
```

### Run complete analysis

```text
POST /analyse
```

Example body:

```json
{
  "ticker": "AAPL",
  "start_date": "2023-01-01",
  "end_date": "2026-01-01"
}
```

### Stream progress

```text
POST /analyse/stream
```

The Streamlit app uses this endpoint so it can show agent progress while the workflow is running.

### Generated files

```text
GET /charts/{filename}
GET /report/{ticker}/pdf
```

## Testing

Run the offline tests with:

```bash
pytest tests/ -q
```

The tests focus on the important deterministic parts of the application, including:

- financial ratios and red flags,
- price KPIs,
- report number provenance,
- graph routing,
- API validation,
- caching,
- serialization.

## Tech stack

- Python
- LangGraph / LangChain
- Groq
- FastAPI
- Streamlit
- pandas / NumPy
- yfinance
- Matplotlib
- Docker
- pytest
