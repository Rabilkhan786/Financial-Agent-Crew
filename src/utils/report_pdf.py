"""Build a simple PDF from the generated report and charts."""

from fpdf import FPDF

from src.components import config
from src.components.logging import get_logger

log = get_logger(__name__)

REPLACEMENTS = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "…": "...",
    "•": "-",
    "₹": "INR ",
    "→": "->",
    "×": "x",
}

CHARTS_BY_SECTION = {
    "Growth": "revenue_profit",
    "Profitability": "margins",
    "Cash generation": "cash_vs_profit",
    "Balance sheet": "debt",
    "Market context": "price",
}


def _clean(text):
    """Replace characters unsupported by FPDF's built-in font."""
    text = str(text or "")
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


def _sections(report):
    """Split markdown level-two headings into ordered sections."""
    sections = []
    heading = None
    body = []

    for line in (report or "").splitlines():
        if line.startswith("## "):
            if heading:
                sections.append((heading, "\n".join(body).strip()))
            heading = line[3:].strip()
            body = []
        elif not line.startswith("# "):
            body.append(line)

    if heading:
        sections.append((heading, "\n".join(body).strip()))
    return sections


def _write_text(pdf, text, size=10, bold=False):
    """Write one text block using the report's standard formatting."""
    style = "B" if bold else ""
    pdf.set_font("Helvetica", style, size)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 6, _clean(text))
    pdf.ln(1)


def build_pdf(crew_state, path=None):
    """Create the report PDF and return its file path."""
    ticker = crew_state.get("ticker", "report")
    company = crew_state.get("company") or ticker
    charts = (crew_state.get("analysis") or {}).get("charts") or {}

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = path or config.OUTPUT_DIR / f"{ticker.replace('.', '_')}_report.pdf"

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    _write_text(pdf, f"{company} ({ticker})", size=17, bold=True)
    _write_text(
        pdf,
        f"Analysis period: {crew_state.get('start_date')} to {crew_state.get('end_date')}",
        size=10,
    )

    for heading, body in _sections(crew_state.get("report", "")):
        _write_text(pdf, heading, size=13, bold=True)
        _write_text(pdf, body)

        chart_path = charts.get(CHARTS_BY_SECTION.get(heading))
        if chart_path:
            try:
                if pdf.get_y() > 200:
                    pdf.add_page()
                pdf.image(chart_path, w=170)
                pdf.ln(4)
            except Exception as error:
                log.warning("Could not add chart %s: %s", chart_path, error)

    pdf.output(str(path))
    log.info("Created PDF %s", path)
    return str(path)
