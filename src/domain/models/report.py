import base64
import io
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal
import re

from fpdf import FPDF

from src.application.entities.analysis_result import AnalysisResult, Section, SummaryItem
from src.application.entities.series_summary import SeriesSummary

# ---------------------------------------------------------------------------
# Unicode sanitisation
# ---------------------------------------------------------------------------

_UNICODE_REPLACEMENTS = str.maketrans({
    ord("—"): "-", ord("–"): "-",
    ord("‘"): "'", ord("’"): "'",
    ord("“"): '"', ord("”"): '"',
    ord("…"): "...",
    ord("·"): "-", ord("•"): "-",
    ord("→"): "->", ord("✓"): "OK",
    ord("■"): "#", ord("×"): "x",
    ord("\U0001f7e2"): "", ord("\U0001f7e1"): "", ord("\U0001f534"): "",
})


def _clean(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = text.translate(_UNICODE_REPLACEMENTS)
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ---------------------------------------------------------------------------
# Dark theme colours
# ---------------------------------------------------------------------------

_PAGE_BG      = (18,  18,  26)   # deep charcoal background
_CARD_BG      = (30,  30,  42)   # card body
_CARD_HDR     = (40,  40,  58)   # card header stripe
_ACCENT_BLUE  = (80, 140, 255)   # header accent / section labels

_TEXT_PRIMARY   = (220, 220, 232)
_TEXT_SECONDARY = (130, 130, 155)
_TEXT_LABEL     = (90,  90, 120)

_GREEN      = (50,  210, 100)
_GREEN_BG   = (20,   55,  35)
_ORANGE     = (255, 160,  50)
_ORANGE_BG  = (60,   42,  15)
_RED        = (255,  80,  80)
_RED_BG     = (60,   18,  18)

_WHITE      = (255, 255, 255)
_IMG_BORDER = (200, 200, 215)   # subtle border around DICOM images

_STATUS_COLOUR: dict[str, tuple] = {
    "normal":      _GREEN,
    "attention":   _ORANGE,
    "significant": _RED,
}
_STATUS_BG: dict[str, tuple] = {
    "normal":      _GREEN_BG,
    "attention":   _ORANGE_BG,
    "significant": _RED_BG,
}
_STATUS_LABEL: dict[str, str] = {
    "normal":      "No significant finding",
    "attention":   "Attention",
    "significant": "Significant finding",
}


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

@dataclass
class Report:
    patient_context: str
    series_summaries: list[SeriesSummary]
    analysis: AnalysisResult
    encoded_images: dict[str, list[str]] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.now)

    def save_to_dir(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._save_markdown(output_dir / "report.md")
        self._save_pdf(output_dir / "report.pdf")

    def _save_markdown(self, path: Path) -> None:
        lines = [
            "# DepthAI - MRI Report",
            f"Generated: {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Clinical Context",
            self.patient_context,
            "",
            "## Series Analysed",
        ]
        for s in self.series_summaries:
            lines.append(f"- {s.label}: {s.slices_total} total slices, {s.slices_analysed} analysed ({s.modality})")
        lines += ["", "## Findings", ""]
        for sec in self.analysis.sections:
            lines.append(f"### {sec.title}  [{sec.status.upper()}]")
            for sub in sec.subsections:
                lines.append(f"#### {sub.title}")
                for f in sub.findings:
                    lines.append(f"- {f}")
            for note in sec.notes:
                lines.append(f"> {note}")
            lines.append("")
        lines += ["## Summary", ""]
        for item in self.analysis.summary:
            lines.append(f"- [{item.status.upper()}] **{item.label}**: {item.text}")
        lines += [
            "",
            "## Clinical Answer",
            f"**Question:** {self.analysis.clinical_answer.question}",
            f"**Answer:** {self.analysis.clinical_answer.answer}",
            f"**Confidence:** {self.analysis.clinical_answer.confidence}",
            f"**Limiting factors:** {self.analysis.clinical_answer.limiting_factors}",
            "",
            "## Radiologist Flags",
        ]
        for flag in self.analysis.flags:
            lines.append(f"- {flag}")
        path.write_text("\n".join(lines), encoding="utf-8")

    def _save_pdf(self, path: Path) -> None:
        pdf = _ReportPDF()
        pdf.build(self)
        pdf.output(str(path))


# ---------------------------------------------------------------------------
# PDF renderer — dark theme
# ---------------------------------------------------------------------------

class _ReportPDF(FPDF):
    M = 18  # page margin

    def normalize_text(self, text: str) -> str:
        s = text.translate(_UNICODE_REPLACEMENTS).encode("latin-1", errors="replace").decode("latin-1")
        return super().normalize_text(s)

    def header(self) -> None:
        # Fill entire page background on every new page
        self.set_fill_color(*_PAGE_BG)
        self.rect(0, 0, 210, 297, "F")

    # ------------------------------------------------------------------ build

    def build(self, report: Report) -> None:
        self.set_margins(self.M, self.M, self.M)
        self.set_auto_page_break(auto=True, margin=self.M)
        self.add_page()

        self._cover(report)
        self._exam_metadata(report)
        self._series_table(report.series_summaries)
        self._section_header("3. DETAILED FINDINGS")

        for sec in report.analysis.sections:
            self._section_card(sec, self._resolve_image(sec, report.encoded_images))

        self._summary_section(report.analysis.summary)
        self._clinical_answer(report.analysis.clinical_answer)
        self._flags_section(report.analysis.flags)
        self._legal_footer()

    # ------------------------------------------------------------------ cover

    def _cover(self, report: Report) -> None:
        # Top accent line
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(0, 0, 210, 3, "F")

        # Title block
        self.set_xy(0, 10)
        self.set_font("Helvetica", "B", 26)
        self.set_text_color(*_TEXT_PRIMARY)
        self.cell(210, 14, "DEPTHAI", align="C", ln=True)

        self.set_font("Helvetica", "", 11)
        self.set_text_color(*_ACCENT_BLUE)
        self.cell(210, 7, "MRI ANALYSIS REPORT", align="C", ln=True)

        self.ln(2)
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(self.M + 20, self.get_y(), self.epw - 40, 1, "F")
        self.ln(5)

        self.set_font("Helvetica", "I", 9)
        self.set_text_color(*_TEXT_SECONDARY)
        self.cell(210, 6, "AI-assisted analysis   |   Mandatory clinical review by a licensed radiologist", align="C", ln=True)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_TEXT_LABEL)
        self.cell(210, 6, f"Generated: {report.generated_at.strftime('%B %d, %Y   %H:%M')}", align="C", ln=True)

        self.ln(14)

    # ------------------------------------------------------------------ exam metadata

    def _exam_metadata(self, report: Report) -> None:
        self._section_header("1. EXAM DATA")

        self.set_x(self.M)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*_TEXT_LABEL)
        self.cell(self.epw, 5, "CLINICAL CONTEXT", ln=True)

        ctx = _clean(report.patient_context)
        x, y = self.M, self.get_y()
        self.set_xy(x + 4, y + 4)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_TEXT_PRIMARY)
        self.multi_cell(self.epw - 8, 5, ctx, fill=False)
        bottom = self.get_y()
        box_h = bottom - y + 5

        self.set_fill_color(*_CARD_BG)
        self.rect(x, y, self.epw, box_h, "F")
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(x, y, 3, box_h, "F")
        self.set_xy(x + 6, y + 4)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_TEXT_PRIMARY)
        self.multi_cell(self.epw - 10, 5, ctx)
        self.set_y(y + box_h + 4)

        fields = [
            ("Series analysed", str(len(report.series_summaries))),
            ("Total slices",    str(sum(s.slices_total for s in report.series_summaries))),
            ("Analysis date",   report.generated_at.strftime("%B %d, %Y")),
        ]
        col_lbl = 30
        col_val = (self.epw / len(fields)) - col_lbl

        self.set_x(self.M)
        for label, value in fields:
            self.set_fill_color(*_CARD_HDR)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*_TEXT_LABEL)
            self.cell(col_lbl, 8, label, border=0, fill=True)
            self.set_fill_color(*_CARD_BG)
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*_TEXT_PRIMARY)
            self.cell(col_val, 8, value, border=0, fill=True)

        self.ln(10)

    # ------------------------------------------------------------------ series table

    def _series_table(self, summaries: list[SeriesSummary]) -> None:
        self._section_header("2. SERIES ANALYSED")

        cw = [97, 26, 28, 23]
        headers = ["Series / Sequence", "Total", "Analysed", "Mod."]

        self.set_x(self.M)
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(*_CARD_HDR)
        self.set_text_color(*_ACCENT_BLUE)
        for i, h in enumerate(headers):
            self.cell(cw[i], 8, h, border=0, fill=True, align="C")
        self.ln()

        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_TEXT_PRIMARY)
        for idx, s in enumerate(summaries):
            self.set_x(self.M)
            fill_c = _CARD_BG if idx % 2 == 0 else _CARD_HDR
            self.set_fill_color(*fill_c)
            self.cell(cw[0], 7, _clean(s.label[:56]), border=0, fill=True)
            self.cell(cw[1], 7, str(s.slices_total),    border=0, fill=True, align="C")
            self.cell(cw[2], 7, str(s.slices_analysed), border=0, fill=True, align="C")
            self.cell(cw[3], 7, s.modality,             border=0, fill=True, align="C")
            self.ln()

        self.ln(5)

    # ------------------------------------------------------------------ section card

    def _resolve_image(self, section: Section, encoded_images: dict[str, list[str]]) -> io.BytesIO | None:
        if not encoded_images or not section.series_label:
            return None
        key = next(
            (k for k in encoded_images
             if section.series_label.lower() in k.lower() or k.lower() in section.series_label.lower()),
            None,
        )
        if not key:
            return None
        slices = encoded_images[key]
        idx = section.best_slice_index
        if idx is None or idx < 0 or idx >= len(slices):
            idx = len(slices) // 2
        return io.BytesIO(base64.b64decode(slices[idx]))

    def _section_card(self, section: Section, img_buf: io.BytesIO | None) -> None:
        colour   = _STATUS_COLOUR.get(section.status, _ACCENT_BLUE)
        bg_card  = _STATUS_BG.get(section.status, _CARD_BG)
        label    = _STATUS_LABEL.get(section.status, "See findings")
        img_size = 44

        text_w = self.epw - (img_size + 6 if img_buf else 0)

        if self.get_y() + (img_size + 6 if img_buf else 20) > 272:
            self.add_page()

        start_page = self.page
        y_start    = self.get_y()

        # Card header row
        self.set_fill_color(*_CARD_HDR)
        self.rect(self.M, y_start, text_w, 10, "F")
        self.set_xy(self.M + 6, y_start + 1)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_TEXT_PRIMARY)
        self.cell(text_w - 55, 8, _clean(section.title))
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*colour)
        self.cell(50, 8, label, align="R", ln=True)
        self.ln(2)

        # Card body background
        body_y = self.get_y()

        # Sub-sections
        for sub in section.subsections:
            self._render_subsection(sub, text_w)

        # Notes
        for note in section.notes:
            self._render_note(note, text_w)

        y_end = self.get_y() + 2

        # Fill card body bg after we know the height
        if self.page == start_page:
            self.set_fill_color(*_CARD_BG)
            self.rect(self.M, body_y - 1, text_w, y_end - body_y + 2, "F")
            # Re-render text on top of background
            self.set_y(body_y)
            for sub in section.subsections:
                self._render_subsection(sub, text_w)
            for note in section.notes:
                self._render_note(note, text_w)
            self.set_y(y_end)

        # DICOM image with white border (same page only)
        if img_buf and self.page == start_page:
            img_x = self.M + text_w + 4
            img_y = y_start + max(0, (y_end - y_start - img_size) / 2)
            if img_y + img_size > 272:
                img_y = y_start
            # White background frame for the grayscale scan
            pad = 2
            self.set_fill_color(*_WHITE)
            self.rect(img_x - pad, img_y - pad, img_size + pad * 2, img_size + pad * 2, "F")
            self.image(img_buf, x=img_x, y=img_y, w=img_size, h=img_size)
            # Subtle border
            self.set_draw_color(*_IMG_BORDER)
            self.set_line_width(0.3)
            self.rect(img_x - pad, img_y - pad, img_size + pad * 2, img_size + pad * 2, "D")
            self.set_line_width(0.2)
            y_end = max(y_end, img_y + img_size + pad + 2)

        # Left accent bar
        if self.page == start_page:
            self.set_fill_color(*colour)
            self.rect(self.M, y_start, 3, y_end - y_start, "F")

        self.set_y(y_end)
        self.ln(5)

    def _render_subsection(self, sub, text_w: float) -> None:
        x = self.M + 6

        self.set_x(x)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*_ACCENT_BLUE)
        self.multi_cell(text_w - 8, 5, _clean(sub.title))
        self.ln(1)

        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_TEXT_PRIMARY)
        for finding in sub.findings:
            self.set_x(x + 2)
            self.multi_cell(text_w - 10, 5, f"  -  {_clean(finding)}")

        self.ln(2)

    def _render_note(self, note: str, text_w: float) -> None:
        x = self.M + 6
        self.set_x(x + 4)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(*_TEXT_SECONDARY)
        self.multi_cell(text_w - 14, 5, _clean(note), fill=False)
        self.ln(1)

    # ------------------------------------------------------------------ summary

    def _summary_section(self, items: list[SummaryItem]) -> None:
        self._section_header("4. SUMMARY OF FINDINGS")

        for item in items:
            colour = _STATUS_COLOUR.get(item.status, _ACCENT_BLUE)
            bg     = _STATUS_BG.get(item.status, _CARD_BG)

            self.set_x(self.M)
            self.set_fill_color(*bg)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*colour)
            self.cell(22, 7, _STATUS_LABEL[item.status][:6].upper(), border=0, fill=True, align="C")
            self.set_fill_color(*_CARD_BG)
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*_TEXT_PRIMARY)
            self.cell(48, 7, _clean(item.label), fill=True)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_TEXT_SECONDARY)
            self.multi_cell(self.epw - 70, 7, _clean(item.text), fill=True)

        self.ln(4)

    # ------------------------------------------------------------------ clinical answer

    def _clinical_answer(self, answer) -> None:
        self._section_header("5. DIRECT ANSWER TO CLINICAL QUESTION")

        rows = [
            ("Clinical question", answer.question),
            ("Image-based answer", answer.answer),
            ("Confidence",         answer.confidence),
            ("Limiting factors",   answer.limiting_factors),
        ]
        lbl_w = 38

        for label, value in rows:
            self.set_x(self.M)
            self.set_fill_color(*_CARD_HDR)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*_TEXT_LABEL)
            self.cell(lbl_w, 7, label, border=0, fill=True)

            self.set_fill_color(*_CARD_BG)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_TEXT_PRIMARY)
            self.multi_cell(self.epw - lbl_w, 7, _clean(value), border=0, fill=True)

        self.ln(4)

    # ------------------------------------------------------------------ flags

    def _flags_section(self, flags: list[str]) -> None:
        self._section_header("6. RADIOLOGIST ATTENTION FLAGS")

        for flag in flags:
            self.set_x(self.M + 4)
            self.set_fill_color(*_CARD_BG)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_TEXT_PRIMARY)
            self.multi_cell(self.epw - 4, 6, f"  -  {_clean(flag)}", fill=True)

        self.ln(4)

    # ------------------------------------------------------------------ helpers

    def _section_header(self, text: str) -> None:
        self.set_fill_color(*_CARD_HDR)
        self.set_text_color(*_ACCENT_BLUE)
        self.set_font("Helvetica", "B", 10)
        self.set_x(self.M)
        # Accent side bar on header
        bar_y = self.get_y()
        self.cell(self.epw, 9, f"    {text}", fill=True, ln=True)
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(self.M, bar_y, 3, 9, "F")
        self.ln(4)

    def _legal_footer(self) -> None:
        self.ln(6)
        self.set_draw_color(*_TEXT_LABEL)
        self.set_line_width(0.2)
        self.line(self.M, self.get_y(), 210 - self.M, self.get_y())
        self.ln(3)
        self.set_x(self.M)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(*_TEXT_LABEL)
        self.multi_cell(
            self.epw, 4.5,
            "This report was generated with AI assistance (DepthAI / GPT-4o) based on direct analysis "
            "of DICOM images and clinical context provided by the user. It does NOT replace an official "
            "radiological report issued by a licensed radiologist, nor a clinical examination. "
            "All clinical decisions must be made exclusively by the responsible physician.",
        )
