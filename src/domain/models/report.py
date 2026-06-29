import base64
import io
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re

from fpdf import FPDF

from src.application.entities.series_summary import SeriesSummary

# ---------------------------------------------------------------------------
# Unicode sanitisation
# ---------------------------------------------------------------------------

_UNICODE_REPLACEMENTS = str.maketrans({
    "—": "-", "–": "-",
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    "…": "...",
    "·": "-", "•": "-",
    "→": "->", "✓": "OK",
    "■": "#", "×": "x",
})

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

_BLUE_DARK  = (22,  60, 120)
_BLUE_MID   = (30,  90, 180)
_BLUE_LIGHT = (235, 242, 255)
_GREEN      = (25, 130,  70)
_GREEN_BG   = (235, 248, 240)
_ORANGE     = (200, 110,  15)
_RED        = (180,  35,  35)
_DARK       = (25,   25,  25)
_GREY_DARK  = (90,   90,  90)
_GREY_LIGHT = (245, 245, 245)
_WHITE      = (255, 255, 255)

_STATUS_MAP = {
    "integro": _GREEN, "intact": _GREEN, "normal": _GREEN,
    "preservad": _GREEN, "no tear": _GREEN, "no evidence": _GREEN,
    "no suture failure": _GREEN, "criteria for suture failure not met": _GREEN,
    "edema": _ORANGE, "derrame": _ORANGE, "mild": _ORANGE,
    "moderate": _ORANGE, "effusion": _ORANGE, "heterogeneous": _ORANGE,
    "rotura": _RED, "ruptur": _RED, "torn": _RED, "fractur": _RED,
    "displaced": _RED, "failure": _RED,
}

_DISCLAIMER_STARTS = (
    "this structured description was generated",
    "this report was generated with ai",
    "note: this",
    "important:",
)


def _status_colour(text: str) -> tuple:
    lower = text.lower()
    for kw, col in _STATUS_MAP.items():
        if kw in lower:
            return col
    return _BLUE_MID


def _status_label(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ("no evidence", "criteria for suture failure not met", "not met", "no tear", "intact", "integro", "normal", "preservad")):
        return "No significant finding"
    if any(k in lower for k in ("edema", "mild", "effusion", "heterogeneous", "post-surgical", "post-repair")):
        return "Attention"
    if any(k in lower for k in ("failure", "torn", "ruptur", "rotura", "displaced", "fractur")):
        return "Significant finding"
    return "See findings"


def _clean(text: str) -> str:
    """Strip markdown bold/italic markers and sanitise unicode."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = text.translate(_UNICODE_REPLACEMENTS)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _is_model_disclaimer(line: str) -> bool:
    lower = line.lower().strip()
    return any(lower.startswith(s) for s in _DISCLAIMER_STARTS)


def _parse_sections(analysis: str) -> list[dict]:
    """Split on ## or ### headings. Each section: {title, lines}."""
    sections: list[dict] = []
    current: dict | None = None

    for raw in analysis.splitlines():
        line = raw.strip()
        if _is_model_disclaimer(line):
            break  # strip model-appended disclaimers

        if re.match(r"^#{1,3} ", line):
            if current is not None:
                sections.append(current)
            heading = re.sub(r"^#+\s*", "", line).strip()
            tag_match = re.search(r"\[([^\]]+)\]\s*$", heading)
            series = tag_match.group(1).strip() if tag_match else None
            title = re.sub(r"\s*\[[^\]]+\]\s*$", "", heading).strip()
            current = {"title": title, "series": series, "lines": []}
        elif current is not None:
            current["lines"].append(line)

    if current is not None:
        sections.append(current)

    if not sections:
        sections = [{"title": "Findings", "series": None, "lines": analysis.splitlines()}]

    return sections


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

@dataclass
class Report:
    patient_context: str
    series_summaries: list[SeriesSummary]
    analysis: str
    encoded_images: dict[str, list[str]] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.now)

    def save_to_dir(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._save_markdown(output_dir / "report.md")
        self._save_pdf(output_dir / "report.pdf")

    def _markdown_content(self) -> str:
        series_lines = "\n".join(
            f"- {s.label}: {s.slices_total} total slices, {s.slices_analysed} analysed ({s.modality})"
            for s in self.series_summaries
        )
        return (
            f"# Deptha - MRI Report\n"
            f"Generated: {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"## Clinical Context\n{self.patient_context}\n\n"
            f"## Series Analysed\n{series_lines}\n\n"
            f"## Findings\n{self.analysis}\n"
        )

    def _save_markdown(self, path: Path) -> None:
        path.write_text(self._markdown_content(), encoding="utf-8")

    def _save_pdf(self, path: Path) -> None:
        pdf = _ReportPDF()
        pdf.build(self)
        pdf.output(str(path))


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------

class _ReportPDF(FPDF):
    M = 18  # margin

    def normalize_text(self, text: str) -> str:
        s = text.translate(_UNICODE_REPLACEMENTS).encode("latin-1", errors="replace").decode("latin-1")
        return super().normalize_text(s)

    # ------------------------------------------------------------------ build

    def build(self, report: Report) -> None:
        self.set_margins(self.M, self.M, self.M)
        self.set_auto_page_break(auto=True, margin=self.M)
        self.add_page()

        self._cover(report)
        self._exam_metadata(report)
        self._series_table(report.series_summaries)
        self._section_header("3. DETAILED FINDINGS")
        for section in _parse_sections(report.analysis):
            self._section_card(section, report.encoded_images)
        self._legal_footer()

    # ------------------------------------------------------------------ cover

    def _cover(self, report: Report) -> None:
        self.set_fill_color(*_BLUE_DARK)
        self.rect(0, 0, 210, 46, "F")

        self.set_xy(0, 9)
        self.set_font("Helvetica", "B", 24)
        self.set_text_color(*_WHITE)
        self.cell(210, 13, "DEPTHA  -  MRI ANALYSIS REPORT", align="C", ln=True)

        self.set_font("Helvetica", "", 10)
        self.set_text_color(170, 205, 255)
        self.cell(210, 7, "AI-assisted analysis   |   Mandatory clinical review by a licensed radiologist", align="C", ln=True)

        self.set_fill_color(*_BLUE_MID)
        self.rect(0, 33, 210, 13, "F")
        self.set_xy(0, 35)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(220, 235, 255)
        self.cell(210, 7, f"Generated: {report.generated_at.strftime('%B %d, %Y   %H:%M')}", align="C")

        self.ln(22)

    # ------------------------------------------------------------------ exam metadata

    def _exam_metadata(self, report: Report) -> None:
        self._section_header("1. EXAM DATA")

        # Clinical context block
        self.set_x(self.M)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*_GREY_DARK)
        self.cell(self.epw, 5, "CLINICAL CONTEXT", ln=True)

        self.set_fill_color(*_BLUE_LIGHT)
        ctx = _clean(report.patient_context)
        x, y = self.M, self.get_y()
        self.rect(x, y, self.epw, 1, "F")  # top border
        self.set_xy(x + 3, y + 3)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK)
        self.multi_cell(self.epw - 6, 5, ctx, fill=False)
        bottom = self.get_y()
        self.set_fill_color(*_BLUE_LIGHT)
        self.rect(x, y, self.epw, bottom - y + 3, "F")
        self.set_xy(x + 3, y + 3)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK)
        self.multi_cell(self.epw - 6, 5, ctx)
        self.set_y(bottom + 4)

        # Short metadata row
        fields = [
            ("Series analysed", str(len(report.series_summaries))),
            ("Total slices",    str(sum(s.slices_total for s in report.series_summaries))),
            ("Analysis date",   report.generated_at.strftime("%B %d, %Y")),
        ]
        col_lbl = 30
        col_val = (self.epw / len(fields)) - col_lbl

        self.set_x(self.M)
        for label, value in fields:
            x0 = self.get_x()
            self.set_fill_color(*_GREY_LIGHT)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*_GREY_DARK)
            self.cell(col_lbl, 8, label, border=1, fill=True)
            self.set_fill_color(*_WHITE)
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*_DARK)
            self.cell(col_val, 8, value, border=1, fill=True)

        self.ln(10)

    # ------------------------------------------------------------------ series table

    def _series_table(self, summaries: list[SeriesSummary]) -> None:
        self._section_header("2. SERIES ANALYSED")

        cw = [97, 26, 28, 23]
        headers = ["Series / Sequence", "Total", "Analysed", "Mod."]

        self.set_x(self.M)
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(*_BLUE_DARK)
        self.set_text_color(*_WHITE)
        for i, h in enumerate(headers):
            self.cell(cw[i], 8, h, border=1, fill=True, align="C")
        self.ln()

        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK)
        for idx, s in enumerate(summaries):
            self.set_x(self.M)
            fill = idx % 2 == 0
            self.set_fill_color(*(_BLUE_LIGHT if fill else _WHITE))
            self.cell(cw[0], 7, s.label[:56], border=1, fill=fill)
            self.cell(cw[1], 7, str(s.slices_total),    border=1, fill=fill, align="C")
            self.cell(cw[2], 7, str(s.slices_analysed), border=1, fill=fill, align="C")
            self.cell(cw[3], 7, s.modality,             border=1, fill=fill, align="C")
            self.ln()

        self.ln(5)

    # ------------------------------------------------------------------ section card

    def _section_card(self, section: dict, encoded_images: dict[str, list[str]] | None = None) -> None:
        title     = _clean(section["title"])
        lines     = section["lines"]
        full_text = " ".join(lines)
        colour    = _status_colour(full_text)
        label     = _status_label(full_text)

        # Resolve image for this section
        img_buf  = None
        img_size = 42  # mm — square thumbnail
        series_key = section.get("series")
        if encoded_images and series_key:
            # fuzzy match: find first series whose label contains the tag
            match = next(
                (k for k in encoded_images if series_key.lower() in k.lower() or k.lower() in series_key.lower()),
                None,
            )
            if match:
                slices = encoded_images[match]
                mid    = slices[len(slices) // 2]
                img_buf = io.BytesIO(base64.b64decode(mid))

        text_w = self.epw - (img_size + 4 if img_buf else 0)
        y_start = self.get_y()

        # Header bar
        self.set_fill_color(245, 247, 252)
        self.set_x(self.M + 4)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_BLUE_DARK)
        self.cell(text_w - 50, 8, title, fill=True)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*colour)
        self.cell(46, 8, label, align="R", ln=True)
        self.ln(1)

        # Body lines (constrained to text column width)
        for line in lines:
            if not line.strip():
                self.ln(2)
                continue
            self._card_line(line, max_w=text_w - 5)

        y_end = self.get_y() + 2

        # Embed image aligned to right of card, vertically centred
        if img_buf:
            img_x = self.M + text_w + 2
            img_y = y_start + max(0, (y_end - y_start - img_size) / 2)
            # ensure image fits on page
            if img_y + img_size > 277:
                img_y = y_start
            self.image(img_buf, x=img_x, y=img_y, w=img_size, h=img_size)
            y_end = max(y_end, img_y + img_size + 2)

        # Left accent bar
        self.set_fill_color(*colour)
        self.rect(self.M, y_start, 3, y_end - y_start, "F")

        self.set_y(y_end)
        self.ln(5)

    def _card_line(self, raw: str, max_w: float | None = None) -> None:
        line = raw.strip()
        x = self.M + 5
        w = (max_w if max_w is not None else self.epw) - 5

        # Blockquote: > text
        if line.startswith("> "):
            content = _clean(line[2:])
            self.set_x(x + 4)
            self.set_font("Helvetica", "I", 9)
            self.set_text_color(*_GREY_DARK)
            self.set_fill_color(*_GREY_LIGHT)
            self.multi_cell(w - 4, 5, content, fill=True)
            return

        # Sub-heading: **bold** only line
        if re.match(r"^\*\*[^*]+\*\*$", line) or re.match(r"^\*\*[^*]+\*\*:?\s*$", line):
            content = _clean(line)
            self.set_x(x)
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*_BLUE_DARK)
            self.ln(1)
            self.set_x(x)
            self.multi_cell(w, 5, content)
            return

        # Bullet
        if line.startswith("- ") or line.startswith("* "):
            content = _clean(line[2:])
            # strip leading ?
            content = content.lstrip("? ")
            self.set_x(x + 2)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_DARK)
            self.multi_cell(w - 2, 5, f"  -  {content}")
            return

        # Plain text
        content = _clean(line)
        if not content.strip():
            return
        self.set_x(x)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK)
        self.multi_cell(w, 5, content)

    # ------------------------------------------------------------------ helpers

    def _section_header(self, text: str) -> None:
        self.set_fill_color(*_BLUE_DARK)
        self.set_text_color(*_WHITE)
        self.set_font("Helvetica", "B", 10)
        self.set_x(self.M)
        self.cell(self.epw, 9, f"  {text}", fill=True, ln=True)
        self.ln(4)

    def _legal_footer(self) -> None:
        self.ln(6)
        self.set_draw_color(*_GREY_DARK)
        self.line(self.M, self.get_y(), 210 - self.M, self.get_y())
        self.ln(3)
        self.set_x(self.M)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(*_GREY_DARK)
        self.multi_cell(
            self.epw, 4.5,
            "This report was generated with AI assistance (Deptha / GPT-4o) based on direct analysis "
            "of DICOM images and clinical context provided by the user. It does NOT replace an official "
            "radiological report issued by a licensed radiologist, nor a clinical examination. "
            "All clinical decisions must be made exclusively by the responsible physician.",
        )
