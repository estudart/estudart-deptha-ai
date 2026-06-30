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
        self.add_page()
        self._section_header("3. DETAILED FINDINGS")

        for sec in report.analysis.sections:
            self._section_card(sec, self._resolve_images(sec, report.encoded_images))

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

        self.ln(8)

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

        self.ln(6)

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

    def _resolve_images(self, section: Section, encoded_images: dict[str, list[str]]) -> list[io.BytesIO]:
        if not encoded_images or not section.series_label:
            return []
        key = next(
            (k for k in encoded_images
             if section.series_label.lower() in k.lower() or k.lower() in section.series_label.lower()),
            None,
        )
        if not key:
            return []
        slices  = encoded_images[key]
        indices = section.best_slice_indices
        if not indices:
            mid     = len(slices) // 2
            indices = [mid]
        valid = [i for i in indices if 0 <= i < len(slices)][:3]
        if not valid:
            valid = [len(slices) // 2]
        return [io.BytesIO(base64.b64decode(slices[i])) for i in valid]

    _IMG_STRIP_H = 46  # height of image strip row

    def _estimate_card_height(self, section: Section, text_w: float, has_images: bool) -> float:
        h = 14  # header + gap
        for sub in section.subsections:
            h += self._count_lines(_clean(sub.title), text_w - 8, 5) * 5 + 3
            for f in sub.findings:
                h += self._count_lines(_clean(f), text_w - 17, 5) * 5 + 1
            h += 2
        if section.reasoning:
            lines = self._count_lines(_clean(section.reasoning), text_w - 20, 5)
            h += lines * 5 + 12
        if section.notes:
            total = sum(self._count_lines(_clean(n), text_w - 20, 5) for n in section.notes)
            h += total * 5 + len(section.notes) * 2 + 12
        if has_images:
            h += self._IMG_STRIP_H + 4
        return h

    def _section_card(self, section: Section, img_bufs: list[io.BytesIO]) -> None:
        colour  = _STATUS_COLOUR.get(section.status, _ACCENT_BLUE)
        label   = _STATUS_LABEL.get(section.status, "See findings")

        text_w  = self.epw
        est_h   = self._estimate_card_height(section, text_w, bool(img_bufs))

        # Page break — keep entire card together
        if self.get_y() + est_h > 272:
            self.add_page()

        y_start = self.get_y()

        # Card body background
        self.set_fill_color(*_CARD_BG)
        self.rect(self.M, y_start + 10, text_w, max(est_h - 10, 20), "F")

        # Card header
        self.set_fill_color(*_CARD_HDR)
        self.rect(self.M, y_start, text_w, 10, "F")
        self.set_xy(self.M + 6, y_start + 1)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_TEXT_PRIMARY)
        title_max_w = text_w - 60
        title = _clean(section.title)
        while self.get_string_width(title) > title_max_w and len(title) > 3:
            title = title[:-1]
        if title != _clean(section.title):
            title = title[:-1] + "..."
        self.cell(title_max_w, 8, title)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*colour)
        self.cell(44, 8, label, align="R")
        self.cell(6, 8, "", ln=True)  # right padding
        self.ln(2)

        # Content — single pass
        for sub in section.subsections:
            self._render_subsection(sub, text_w)
        if section.reasoning:
            self._render_reasoning(section.reasoning, text_w)
        if section.notes:
            self._render_notes(section.notes, text_w)

        # Image strip
        if img_bufs:
            self._render_image_strip(img_bufs, text_w)

        y_end = self.get_y() + 2

        # Left accent bar
        self.set_fill_color(*colour)
        self.rect(self.M, y_start, 3, y_end - y_start, "F")

        self.set_y(y_end)
        self.ln(4)

    def _render_image_strip(self, img_bufs: list[io.BytesIO], text_w: float) -> None:
        n       = len(img_bufs)
        gap     = 3
        pad     = 2
        # subtract pads from both outer edges so strip stays within card bounds
        strip_w = text_w - pad * 2
        img_w   = (strip_w - gap * (n - 1)) / n
        img_h   = self._IMG_STRIP_H
        strip_y = self.get_y() + 3
        x0      = self.M + pad  # start inset by one pad

        for i, buf in enumerate(img_bufs):
            x = x0 + i * (img_w + gap)
            self.set_fill_color(*_WHITE)
            self.rect(x - pad, strip_y - pad, img_w + pad * 2, img_h + pad * 2, "F")
            self.image(buf, x=x, y=strip_y, w=img_w, h=img_h)
            self.set_draw_color(*_IMG_BORDER)
            self.set_line_width(0.3)
            self.rect(x - pad, strip_y - pad, img_w + pad * 2, img_h + pad * 2, "D")
            self.set_line_width(0.2)

        self.set_y(strip_y + img_h + pad + 2)

    def _render_subsection(self, sub, text_w: float) -> None:
        x = self.M + 6
        bullet_w = 5
        text_indent = x + bullet_w

        self.set_x(x)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*_ACCENT_BLUE)
        self.multi_cell(text_w - 8, 5, _clean(sub.title))
        self.ln(1)

        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_TEXT_PRIMARY)
        for finding in sub.findings:
            # Bullet dash fixed-width, then text with hanging indent
            bullet_y = self.get_y()
            self.set_xy(x + 2, bullet_y)
            self.cell(bullet_w, 5, "-")
            self.set_xy(text_indent + 2, bullet_y)
            self.multi_cell(text_w - bullet_w - 12, 5, _clean(finding))

        self.ln(2)

    def _render_reasoning(self, reasoning: str, text_w: float) -> None:
        x = self.M + 6
        pad = 4
        inner_w = text_w - 8 - pad * 2

        # Measure block height
        self.set_font("Helvetica", "I", 8.5)
        lines = self._count_lines(_clean(reasoning), inner_w, 5)
        block_h = 5 + lines * 5 + pad  # label row + text rows + bottom pad

        y = self.get_y()

        # Subtle tinted background
        self.set_fill_color(38, 38, 55)
        self.rect(x, y, text_w - 8, block_h, "F")

        # Thin left accent line
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(x, y, 2, block_h, "F")

        # Label
        self.set_xy(x + pad + 2, y + 3)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*_ACCENT_BLUE)
        self.cell(inner_w, 4, "REASONING", ln=True)

        # Text
        self.set_x(x + pad + 2)
        self.set_font("Helvetica", "I", 8.5)
        self.set_text_color(*_TEXT_SECONDARY)
        self.multi_cell(inner_w, 5, _clean(reasoning), fill=False)

        self.set_y(y + block_h + 2)

    def _render_notes(self, notes: list[str], text_w: float) -> None:
        x   = self.M + 6
        pad = 4
        bullet_w  = 5
        inner_w   = text_w - 8 - pad * 2 - bullet_w
        line_h    = 5

        # Measure total block height: label row + all bullet lines
        total_lines = sum(self._count_lines(_clean(n), inner_w, line_h) for n in notes)
        block_h = 5 + total_lines * line_h + len(notes) * 2 + pad

        y = self.get_y()

        # Background — slightly different shade from reasoning
        self.set_fill_color(28, 28, 42)
        self.rect(x, y, text_w - 8, block_h, "F")

        # Thin left accent in status-muted colour
        self.set_fill_color(*_TEXT_LABEL)
        self.rect(x, y, 2, block_h, "F")

        # Label
        self.set_xy(x + pad + 2, y + 3)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*_TEXT_LABEL)
        self.cell(inner_w, 4, "OBSERVATIONS", ln=True)

        # Bullet items
        self.set_font("Helvetica", "I", 8.5)
        self.set_text_color(*_TEXT_SECONDARY)
        for note in notes:
            bullet_y = self.get_y()
            self.set_xy(x + pad + 2, bullet_y)
            self.cell(bullet_w, line_h, "-")
            self.set_xy(x + pad + 2 + bullet_w, bullet_y)
            self.multi_cell(inner_w, line_h, _clean(note), fill=False)
            self.ln(1)

        self.set_y(y + block_h + 2)

    # ------------------------------------------------------------------ summary

    def _summary_section(self, items: list[SummaryItem]) -> None:
        self._section_header("4. SUMMARY OF FINDINGS")

        pill_w  = 20
        lbl_w   = 55
        text_w  = self.epw - pill_w - lbl_w
        line_h  = 5.5

        for idx, item in enumerate(items):
            colour = _STATUS_COLOUR.get(item.status, _ACCENT_BLUE)
            bg     = _STATUS_BG.get(item.status, _CARD_BG)

            # Pre-measure value height
            self.set_font("Helvetica", "", 9)
            lines = self._count_lines(_clean(item.text), text_w, line_h)
            row_h = max(lines * line_h + 4, 10)

            # Page break guard — keep entire row together
            if self.get_y() + row_h > 272:
                self.add_page()

            row_y = self.get_y()
            alt   = _CARD_BG if idx % 2 == 0 else _CARD_HDR

            # Backgrounds
            self.set_fill_color(*bg)
            self.rect(self.M, row_y, pill_w, row_h, "F")
            self.set_fill_color(*alt)
            self.rect(self.M + pill_w, row_y, lbl_w, row_h, "F")
            self.rect(self.M + pill_w + lbl_w, row_y, text_w, row_h, "F")

            # Status pill (vertically centred)
            self.set_xy(self.M, row_y + (row_h - 4) / 2 - 1)
            self.set_font("Helvetica", "B", 7.5)
            self.set_text_color(*colour)
            self.cell(pill_w, 4, _STATUS_LABEL[item.status][:6].upper(), align="C")

            # Label — truncate to fit column width
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*_TEXT_PRIMARY)
            label_text = _clean(item.label)
            while self.get_string_width(label_text) > lbl_w - 4 and len(label_text) > 3:
                label_text = label_text[:-1]
            if label_text != _clean(item.label):
                label_text = label_text[:-1] + "..."
            self.set_xy(self.M + pill_w + 2, row_y + (row_h - 4) / 2 - 1)
            self.cell(lbl_w - 2, 4, label_text)

            # Value text
            self.set_xy(self.M + pill_w + lbl_w + 3, row_y + 2)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_TEXT_SECONDARY)
            self.multi_cell(text_w - 6, line_h, _clean(item.text))

            self.set_y(row_y + row_h)

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
        lbl_w  = 38
        val_w  = self.epw - lbl_w
        line_h = 5.5

        for idx, (label, value) in enumerate(rows):
            # Measure how tall the value will be
            self.set_font("Helvetica", "", 9)
            lines = self._count_lines(_clean(value), val_w, line_h)
            row_h = max(lines * line_h + 4, 10)

            if self.get_y() + row_h > 272:
                self.add_page()

            row_y = self.get_y()

            # Label background
            lbl_c = _CARD_HDR if idx % 2 == 0 else (35, 35, 50)
            self.set_fill_color(*lbl_c)
            self.rect(self.M, row_y, lbl_w, row_h, "F")

            # Value background
            val_c = _CARD_BG if idx % 2 == 0 else (26, 26, 38)
            self.set_fill_color(*val_c)
            self.rect(self.M + lbl_w, row_y, val_w, row_h, "F")

            # Label text (vertically centred)
            self.set_xy(self.M + 3, row_y + (row_h - 4) / 2 - 1)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*_TEXT_LABEL)
            self.cell(lbl_w - 3, 4, label)

            # Value text
            self.set_xy(self.M + lbl_w + 3, row_y + 2)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_TEXT_PRIMARY)
            self.multi_cell(val_w - 6, line_h, _clean(value))

            self.set_y(row_y + row_h)

        self.ln(4)

    def _count_lines(self, text: str, width: float, line_h: float) -> int:
        """Estimate number of lines multi_cell will produce for given width."""
        self.set_font("Helvetica", "", 9)
        words = text.split()
        lines, current = 1, ""
        for word in words:
            test = (current + " " + word).strip()
            if self.get_string_width(test) > width - 6:
                lines += 1
                current = word
            else:
                current = test
        return lines

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
        bar_y = self.get_y()
        self.cell(self.epw, 9, f"    {text}", fill=True, ln=True)
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(self.M, bar_y, 3, 9, "F")
        self.ln(3)

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
