"""Turns the finished report into a PDF.

Two fpdf2 details worth knowing, both learned the hard way:

1. The built-in fonts only handle latin-1. A smart quote or a dash copied out
   of a news headline crashes the whole export, so every string is cleaned
   first.
2. After an image or a table, the cursor can be left somewhere unexpected and
   the next block of text comes out squashed. Calling set_x(l_margin) before
   each multi_cell puts it back at the left margin every time.
"""

from fpdf import FPDF

from src import config

log = config.get_logger(__name__)

# Characters the built-in fonts cannot print, and what to use instead.
REPLACEMENTS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
    "•": "-", "₹": "INR ", "→": "->", "×": "x",
}

# The order sections appear in. Anything else the writer produced is added
# after these, so nothing is silently dropped.
SECTION_ORDER = [
    "Executive summary", "Business quality", "Growth", "Profitability",
    "Cash generation", "Balance sheet", "Valuation", "Market context",
    "Red flags", "Recommendation", "Data notes",
]

# Which chart goes under which section.
CHARTS_BY_SECTION = {
    "Growth": "revenue_profit",
    "Profitability": "margins",
    "Cash generation": "cash_vs_profit",
    "Balance sheet": "debt",
    "Market context": "price",
}


def clean(text):
    """Make a string safe for the PDF fonts."""
    if text is None:
        return ""
    text = str(text)
    for bad, good in REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def split_sections(report):
    """Break the markdown report into {heading: body}."""
    sections = {}
    heading = None
    lines = []
    for line in (report or "").splitlines():
        if line.startswith("## "):
            if heading:
                sections[heading] = "\n".join(lines).strip()
            heading = line[3:].strip()
            lines = []
        elif line.startswith("# "):
            continue                      # the title is drawn separately
        else:
            lines.append(line)
    if heading:
        sections[heading] = "\n".join(lines).strip()
    return sections


class ReportPDF(FPDF):
    """A PDF with a page number in the footer."""

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def write_paragraph(pdf, text, size=10, style=""):
    """One block of text, always starting at the left margin."""
    pdf.set_font("Helvetica", style, size)
    pdf.set_x(pdf.l_margin)               # see the note at the top of the file
    pdf.multi_cell(0, 5.5, clean(text))
    pdf.ln(2)


def write_heading(pdf, text):
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 7, clean(text))
    pdf.ln(1)


def write_chart(pdf, path):
    """Put a chart in, starting a new page if it will not fit."""
    if not path:
        return
    try:
        if pdf.get_y() > 200:
            pdf.add_page()
        pdf.image(path, w=170)
        pdf.ln(4)
    except Exception as error:
        log.warning("could not add chart %s: %s", path, error)


def build_pdf(crew_state, path=None):
    """Write the whole report out as a PDF and return the file path."""
    ticker = crew_state.get("ticker", "report")
    company = crew_state.get("company") or ticker
    charts = crew_state.get("analysis", {}).get("charts", {}) or {}

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        path = config.OUTPUT_DIR / f"{ticker.replace('.', '_')}_report.pdf"

    pdf = ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # --- Header ---
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 9, clean(f"{company} ({ticker})"))
    write_paragraph(pdf, f"Fundamental analysis - {crew_state.get('start_date')} to "
                         f"{crew_state.get('end_date')}", size=10, style="I")

    fundamentals = crew_state.get("fundamentals", {})
    if fundamentals.get("years"):
        write_paragraph(pdf, f"Based on {fundamentals['years']} financial years, "
                             f"reported in {fundamentals.get('currency') or 'the local currency'}. "
                             f"Latest year end {fundamentals.get('period_end')}.",
                        size=9, style="I")

    # --- The report itself ---
    sections = split_sections(crew_state.get("report", ""))
    written = set()

    for heading in SECTION_ORDER:
        if heading not in sections:
            continue
        write_heading(pdf, heading)
        write_paragraph(pdf, sections[heading])
        write_chart(pdf, charts.get(CHARTS_BY_SECTION.get(heading)))
        written.add(heading)

    for heading, body in sections.items():
        if heading not in written:
            write_heading(pdf, heading)
            write_paragraph(pdf, body)

    # --- Appendix: what the agents said ---
    log_entries = crew_state.get("conversation_log", [])
    if log_entries:
        pdf.add_page()
        write_heading(pdf, "Appendix: agent conversation log")
        write_paragraph(pdf, "Each step the crew took, in order. Revisions appear "
                             "where the reviewer sent work back.", size=9, style="I")
        for number, entry in enumerate(log_entries, start=1):
            write_paragraph(pdf, f"{number}. {entry.get('agent')}: {entry.get('message')}",
                            size=9)

    errors = crew_state.get("errors", [])
    if errors:
        write_heading(pdf, "Problems during the run")
        for problem in errors:
            write_paragraph(pdf, f"- {problem}", size=9)

    pdf.output(str(path))
    log.info("wrote PDF %s", path)
    return str(path)
