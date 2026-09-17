"""FastAPI backend for the financial analysis crew."""

import datetime as dt
import json
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.components import config
from src.components.logging import get_logger
from src.core import graph
from src.utils import report_pdf, serialization

log = get_logger(__name__)

app = FastAPI(
    title="Financial Research Agent API",
    description="Runs the LangGraph financial analysis workflow.",
    version="1.0.0",
)


class AnalysisRequest(BaseModel):
    """Input required for one analysis run."""

    ticker: str = Field(min_length=1, max_length=20)
    start_date: dt.date
    end_date: dt.date


def _dates(request):
    if request.start_date > request.end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )
    return request.start_date.isoformat(), request.end_date.isoformat()


def _result(state):
    """Convert the final LangGraph state into an API response."""
    pdf_url = None
    if state.get("report"):
        try:
            report_pdf.build_pdf(state)
            pdf_url = f"/report/{state.get('ticker')}/pdf"
        except Exception as error:
            log.error("PDF generation failed: %s", error)

    result = serialization.to_jsonable(state)
    result["analysis"] = result.get("analysis") or {}

    charts = (state.get("analysis") or {}).get("charts") or {}
    result["analysis"]["charts"] = {
        name: f"/charts/{pathlib.Path(path).name}"
        for name, path in charts.items()
    }
    result["pdf_url"] = pdf_url
    return result


@app.get("/health")
def health():
    """Return backend readiness."""
    missing = config.missing_required()
    return {
        "status": "ok" if not missing else "not configured",
        "model": config.GROQ_MODEL,
        "missing_config": missing,
        "sources": config.enabled_sources(),
    }


@app.post("/analyse")
def analyse(request: AnalysisRequest):
    """Run the complete workflow and return the final result."""
    start_date, end_date = _dates(request)

    try:
        state = graph.run_crew(request.ticker, start_date, end_date)
    except Exception as error:
        log.exception("Analysis failed for %s", request.ticker)
        raise HTTPException(status_code=500, detail=str(error)) from error

    return _result(state)


@app.post("/analyse/stream")
def analyse_stream(request: AnalysisRequest):
    """Stream agent progress and then the final result."""
    start_date, end_date = _dates(request)

    def events():
        shown = 0
        latest_state = None

        try:
            for snapshot in graph.stream_crew(
                request.ticker,
                start_date,
                end_date,
            ):
                latest_state = snapshot
                log_entries = snapshot.get("conversation_log", [])

                for entry in log_entries[shown:]:
                    shown += 1
                    yield json.dumps(
                        {
                            "event": "progress",
                            "agent": entry.get("agent"),
                            "message": entry.get("message"),
                        }
                    ) + "\n"
        except Exception as error:
            log.exception("Streaming analysis failed for %s", request.ticker)
            yield json.dumps(
                {"event": "error", "detail": str(error)}
            ) + "\n"
            return

        if latest_state is None:
            yield json.dumps(
                {"event": "error", "detail": "No result was produced."}
            ) + "\n"
            return

        yield json.dumps(
            {"event": "result", "result": _result(latest_state)}
        ) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/charts/{filename}")
def chart(filename: str):
    """Serve one generated PNG chart."""
    safe_name = pathlib.Path(filename).name
    if safe_name != filename or not filename.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Invalid chart filename")

    path = config.OUTPUT_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Chart not found")

    return FileResponse(path, media_type="image/png")


@app.get("/report/{ticker}/pdf")
def report(ticker: str):
    """Serve the generated PDF report."""
    if pathlib.Path(ticker).name != ticker:
        raise HTTPException(status_code=400, detail="Invalid ticker")

    path = config.OUTPUT_DIR / f"{ticker.replace('.', '_')}_report.pdf"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{ticker}_report.pdf",
    )
