"""This is the FastAPI service. It runs the crew and sends back the report.
The Streamlit app calls this instead of running the crew itself.

    uvicorn api:app --reload --port 8000

Endpoints:

    GET  /health              is it up, and is the model key configured
    POST /analyse             run the crew, return the whole result as JSON
    POST /analyse/stream      the same run, but as newline-delimited JSON so a
                              client can show each agent as it finishes
    GET  /charts/{filename}   the PNGs the data analyst drew
    GET  /report/{ticker}/pdf the finished report as a PDF
"""

import json
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from src import config, graph, report_pdf, serialise

log = config.get_logger(__name__)

app = FastAPI(
    title="Financial Research Agent API",
    description="Runs a LangGraph crew over one US ticker and returns a "
                "fundamental analysis report. Informational only, not "
                "investment advice.",
    version="1.0.0",
)


class AnalysisRequest(BaseModel):
    """What the client has to send to start a run."""

    ticker: str = Field(description="A US listing, for example AAPL")
    start_date: str = Field(description="ISO date, for example 2023-01-01")
    end_date: str = Field(description="ISO date, for example 2026-01-01")


def chart_urls(state):
    """Rewrite chart file paths as URLs this API can serve.

    The paths in the state point at the API server's own disk, which means
    nothing to a client on another machine. Only the filename survives.
    """
    charts = (state.get("analysis") or {}).get("charts") or {}
    return {name: f"/charts/{pathlib.Path(path).name}" for name, path in charts.items()}


def build_result(state):
    """The crew state, ready to send: JSON-safe, with URLs instead of paths."""
    result = serialise.to_jsonable(state)

    # Written on this side because report_pdf needs the real chart paths and
    # the full state; the client only ever sees the URL.
    pdf_url = None
    if state.get("report"):
        try:
            report_pdf.build_pdf(state)
            pdf_url = f"/report/{state.get('ticker')}/pdf"
        except Exception as error:
            log.error("could not build the PDF for %s: %s", state.get("ticker"), error)

    result["analysis"] = result.get("analysis") or {}
    result["analysis"]["charts"] = chart_urls(state)
    result["pdf_url"] = pdf_url
    return result


@app.get("/health")
def health():
    """Whether the service can actually run anything."""
    missing = config.missing_required()
    return {
        "status": "ok" if not missing else "not configured",
        "model": config.GROQ_MODEL,
        "missing_config": missing,
        "sources": config.enabled_sources(),
    }


@app.post("/analyse")
def analyse(request: AnalysisRequest):
    """Run the whole crew and return the finished result in one response."""
    log.info("api: analyse %s", request.ticker)
    try:
        state = graph.run_crew(request.ticker, request.start_date, request.end_date)
    except Exception as error:
        log.error("api: crew failed for %s: %s", request.ticker, error)
        raise HTTPException(status_code=500, detail=f"the crew failed: {error}")
    return build_result(state)


@app.post("/analyse/stream")
def analyse_stream(request: AnalysisRequest):
    """The same run, streamed as newline-delimited JSON.

    One object per line. Progress lines carry the agent that just finished, so
    the client can show the crew working instead of a two-minute blank spinner;
    the last line carries the finished result. A failure is sent as a line too,
    rather than a half-written stream the client cannot tell apart from a
    network drop.
    """
    def lines():
        shown = 0
        state = None
        try:
            for snapshot in graph.stream_crew(request.ticker, request.start_date,
                                              request.end_date):
                state = snapshot
                entries = snapshot.get("conversation_log", [])
                for entry in entries[shown:]:
                    shown += 1
                    yield json.dumps({"event": "progress", "agent": entry.get("agent"),
                                      "message": entry.get("message")}) + "\n"
        except Exception as error:
            log.error("api: crew failed for %s: %s", request.ticker, error)
            yield json.dumps({"event": "error", "detail": str(error)}) + "\n"
            return

        if state is None:
            yield json.dumps({"event": "error",
                              "detail": "the crew produced no result"}) + "\n"
            return

        yield json.dumps({"event": "result", "result": build_result(state)}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.get("/charts/{filename}")
def chart(filename: str):
    """One of the PNGs the data analyst drew."""
    # Must be a bare filename, no directory part - stops a crafted name from
    # reaching outside the output folder.
    if pathlib.Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="bad filename")
    path = config.OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="no such chart")
    return FileResponse(path, media_type="image/png")


@app.get("/report/{ticker}/pdf")
def report(ticker: str):
    """The finished report as a PDF, if one has been built for this ticker."""
    if pathlib.Path(ticker).name != ticker:
        raise HTTPException(status_code=400, detail="bad ticker")
    path = config.OUTPUT_DIR / f"{ticker.replace('.', '_')}_report.pdf"
    if not path.exists():
        raise HTTPException(status_code=404,
                            detail="no report has been built for that ticker yet")
    return FileResponse(path, media_type="application/pdf",
                        filename=f"{ticker}_report.pdf")
