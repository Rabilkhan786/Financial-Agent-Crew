"""FastAPI service for the financial research crew.

Run with:

    uvicorn api:app --reload --port 8000
"""

import datetime as dt
import json
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from src import config, graph, report_pdf, serialise

log = config.get_logger(__name__)

app = FastAPI(
    title="Financial Research Agent API",
    description=(
        "Runs a LangGraph crew over one ticker and returns a fundamental "
        "analysis report. Informational only, not investment advice."
    ),
    version="1.0.0",
)


class AnalysisRequest(BaseModel):
    """Input required to start one analysis run."""

    ticker: str = Field(
        min_length=1,
        max_length=20,
        description="Ticker, for example AAPL",
    )
    start_date: dt.date = Field(description="Start date, for example 2023-01-01")
    end_date: dt.date = Field(description="End date, for example 2026-01-01")


def request_dates(request):
    """Validate the date range and return ISO strings for the graph layer."""
    if request.start_date > request.end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )
    return request.start_date.isoformat(), request.end_date.isoformat()


def chart_urls(state):
    """Rewrite local chart paths as URLs this API can serve."""
    charts = (state.get("analysis") or {}).get("charts") or {}
    return {
        name: f"/charts/{pathlib.Path(path).name}"
        for name, path in charts.items()
    }


def build_result(state):
    """Convert crew state into a JSON-safe API response."""
    result = serialise.to_jsonable(state)

    pdf_url = None
    if state.get("report"):
        try:
            report_pdf.build_pdf(state)
            pdf_url = f"/report/{state.get('ticker')}/pdf"
        except Exception as error:
            # PDF generation is optional output. Keep the analysis available
            # even when PDF creation fails, but make the failure visible.
            log.error(
                "could not build the PDF for %s: %s",
                state.get("ticker"),
                error,
            )

    result["analysis"] = result.get("analysis") or {}
    result["analysis"]["charts"] = chart_urls(state)
    result["pdf_url"] = pdf_url
    return result


@app.get("/health")
def health():
    """Return service readiness and configured data sources."""
    missing = config.missing_required()
    return {
        "status": "ok" if not missing else "not configured",
        "model": config.GROQ_MODEL,
        "missing_config": missing,
        "sources": config.enabled_sources(),
    }


@app.post("/analyse")
def analyse(request: AnalysisRequest):
    """Run the whole crew and return the finished result."""
    start_date, end_date = request_dates(request)
    log.info("api: analyse %s", request.ticker)

    try:
        state = graph.run_crew(request.ticker, start_date, end_date)
    except Exception as error:
        log.error("api: crew failed for %s: %s", request.ticker, error)
        raise HTTPException(
            status_code=500,
            detail=f"the crew failed: {error}",
        ) from error

    return build_result(state)


@app.post("/analyse/stream")
def analyse_stream(request: AnalysisRequest):
    """Run the crew and stream progress as newline-delimited JSON."""
    start_date, end_date = request_dates(request)

    def lines():
        shown = 0
        state = None

        try:
            for snapshot in graph.stream_crew(
                request.ticker,
                start_date,
                end_date,
            ):
                state = snapshot
                entries = snapshot.get("conversation_log", [])
                for entry in entries[shown:]:
                    shown += 1
                    yield json.dumps(
                        {
                            "event": "progress",
                            "agent": entry.get("agent"),
                            "message": entry.get("message"),
                        }
                    ) + "\n"
        except Exception as error:
            log.error("api: crew failed for %s: %s", request.ticker, error)
            yield json.dumps({"event": "error", "detail": str(error)}) + "\n"
            return

        if state is None:
            yield json.dumps(
                {"event": "error", "detail": "the crew produced no result"}
            ) + "\n"
            return

        yield json.dumps(
            {"event": "result", "result": build_result(state)}
        ) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.get("/charts/{filename}")
def chart(filename: str):
    """Serve one generated PNG chart."""
    if pathlib.Path(filename).name != filename or pathlib.Path(filename).suffix.lower() != ".png":
        raise HTTPException(status_code=400, detail="bad chart filename")

    path = config.OUTPUT_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no such chart")

    return FileResponse(path, media_type="image/png")


@app.get("/report/{ticker}/pdf")
def report(ticker: str):
    """Serve a generated PDF report for one ticker."""
    if pathlib.Path(ticker).name != ticker:
        raise HTTPException(status_code=400, detail="bad ticker")

    path = config.OUTPUT_DIR / f"{ticker.replace('.', '_')}_report.pdf"
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="no report has been built for that ticker yet",
        )

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{ticker}_report.pdf",
    )
