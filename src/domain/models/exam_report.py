"""
ExamReport — multi-file output model for the section-based pipeline.

Output layout:
    output_dir/
        sections/
            01_ligaments/
                report.md
                report.pdf
            02_menisci/
                report.md
                report.pdf
            ...
        summary/
            report.md
            report.pdf

Domain model — no LLM, no infrastructure imports.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from src.application.entities.section_result import SectionResult, SubsectionFinding
from src.application.entities.synthesis_result import SynthesisResult, SummaryItem

# ---------------------------------------------------------------------------
# Unicode sanitisation
# ---------------------------------------------------------------------------

_UNICODE_REPLACEMENTS = str.maketrans({
    ord("—"): "-", ord("–"): "-",
    ord("'"): "'", ord("'"): "'",
    ord("“"): '"', ord("”"): '"',
    ord("…"): "...",
    ord("·"): "-", ord("•"): "-",
    ord("→"): "->", ord("✓"): "OK",
    ord("■"): "#", ord("×"): "x",
})


def _clean(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = text.translate(_UNICODE_REPLACEMENTS)
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ---------------------------------------------------------------------------
# Dark theme colours (shared)
# ---------------------------------------------------------------------------

_PAGE_BG      = (18,  18,  26)
_CARD_BG      = (30,  30,  42)
_CARD_HDR     = (40,  40,  58)
_ACCENT_BLUE  = (80, 140, 255)

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
_IMG_BORDER = (200, 200, 215)

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
    "normal":      "Normal",
    "attention":   "Attention",
    "significant": "Significant",
}


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

@dataclass
class ExamReport:
    patient_context: str
    clinical_question: str
    laterality: str | None
    sections: list[SectionResult]
    synthesis: SynthesisResult
    generated_at: datetime = field(default_factory=datetime.now)

    def save_to_dir(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        sections_dir = output_dir / "sections"
        sections_dir.mkdir(exist_ok=True)

        for section in self.sections:
            sec_dir = sections_dir / section.section_folder
            sec_dir.mkdir(exist_ok=True)
            self._save_section_markdown(section, sec_dir / "report.md")
            self._save_section_pdf(section, sec_dir / "report.pdf")

        summary_dir = output_dir / "summary"
        summary_dir.mkdir(exist_ok=True)
        self._save_summary_markdown(summary_dir / "report.md")
        self._save_summary_pdf(summary_dir / "report.pdf")

    # ------------------------------------------------------------------
    # Section markdown
    # ------------------------------------------------------------------

    def _save_section_markdown(self, section: SectionResult, path: Path) -> None:
        lines = [
            f"# {section.section_title}",
            f"**Status:** {section.status.upper()}",
            f"Generated: {self.generated_at.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Clinical Context",
            self.patient_context,
            "",
            "## Findings",
        ]
        for sub in section.subsections:
            lines.append(f"### {sub.title}")
            for f in sub.findings:
                lines.append(f"- {f}")
        lines += ["", "## Reasoning", section.reasoning, ""]
        if section.notes:
            lines.append("## Observations")
            for n in section.notes:
                lines.append(f"> {n}")
        if section.images_used:
            lines += ["", "## Images Used"]
            for img in section.images_used:
                lines.append(f"- `{img}`")
        path.write_text("\n".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # Summary markdown
    # ------------------------------------------------------------------

    def _save_summary_markdown(self, path: Path) -> None:
        syn = self.synthesis
        lines = [
            "# DepthAI — MRI Synthesis Report",
            f"Generated: {self.generated_at.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Clinical Context",
            self.patient_context,
            "",
            "## Summary of Findings",
        ]
        for item in syn.summary:
            lines.append(f"- [{item.status.upper()}] **{item.label}**: {item.text}")
        lines += [
            "",
            "## Clinical Answer",
            f"**Question:** {syn.clinical_answer.question}",
            f"**Answer:** {syn.clinical_answer.answer}",
            f"**Confidence:** {syn.clinical_answer.confidence}",
            f"**Limiting factors:** {syn.clinical_answer.limiting_factors}",
            "",
            "## Radiologist Flags",
        ]
        for flag in syn.flags:
            lines.append(f"- {flag}")
        lines += [
            "",
            "## Section Status Overview",
        ]
        for sec in self.sections:
            lines.append(f"- **{sec.section_title}**: {sec.status.upper()}")
        path.write_text("\n".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # PDF helpers
    # ------------------------------------------------------------------

    def _save_section_pdf(self, section: SectionResult, path: Path) -> None:
        pdf = _SectionPDF()
        pdf.build_section(section, self.patient_context, self.generated_at, self.laterality)
        pdf.output(str(path))

    def _save_summary_pdf(self, path: Path) -> None:
        pdf = _SummaryPDF()
        pdf.build_summary(self.synthesis, self.sections, self.patient_context, self.generated_at)
        pdf.output(str(path))


# ---------------------------------------------------------------------------
# Base PDF class — shared styles
# ---------------------------------------------------------------------------

class _BasePDF(FPDF):
    M = 18  # page margin

    def normalize_text(self, text: str) -> str:
        s = text.translate(_UNICODE_REPLACEMENTS).encode("latin-1", errors="replace").decode("latin-1")
        return super().normalize_text(s)

    def header(self) -> None:
        self.set_fill_color(*_PAGE_BG)
        self.rect(0, 0, 210, 297, "F")

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

    def _count_lines(self, text: str, width: float, line_h: float) -> int:
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

    def _cover_header(self, title: str, subtitle: str, generated_at: datetime) -> None:
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(0, 0, 210, 3, "F")
        self.set_xy(0, 10)
        self.set_font("Helvetica", "B", 26)
        self.set_text_color(*_TEXT_PRIMARY)
        self.cell(210, 14, "DEPTHAI", align="C", ln=True)
        self.set_font("Helvetica", "", 11)
        self.set_text_color(*_ACCENT_BLUE)
        self.cell(210, 7, title, align="C", ln=True)
        self.ln(2)
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(self.M + 20, self.get_y(), self.epw - 40, 1, "F")
        self.ln(5)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(*_TEXT_SECONDARY)
        self.cell(210, 6, subtitle, align="C", ln=True)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_TEXT_LABEL)
        self.cell(210, 6, f"Generated: {generated_at.strftime('%B %d, %Y   %H:%M')}", align="C", ln=True)
        self.ln(8)

    def _legal_footer(self) -> None:
        # Disable auto page break so the footer never wraps onto a new blank page
        # (set_y(-22) places us near the bottom margin where multi_cell would
        # otherwise trigger a page break mid-sentence).
        self.set_auto_page_break(False)
        self.set_y(-22)
        self.set_draw_color(*_TEXT_LABEL)
        self.set_line_width(0.2)
        self.line(self.M, self.get_y(), 210 - self.M, self.get_y())
        self.ln(2)
        self.set_x(self.M)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*_TEXT_LABEL)
        self.multi_cell(
            self.epw, 4,
            "This report was generated with AI assistance (DepthAI). "
            "It does NOT replace an official radiological report by a licensed radiologist. "
            "All clinical decisions must be made exclusively by the responsible physician.",
        )
        self.set_auto_page_break(True, margin=self.M)


# ---------------------------------------------------------------------------
# Section PDF
# ---------------------------------------------------------------------------

class _SectionPDF(_BasePDF):

    def build_section(
        self,
        section: SectionResult,
        patient_context: str,
        generated_at: datetime,
        laterality: str | None,
    ) -> None:
        self.set_margins(self.M, self.M, self.M)
        self.set_auto_page_break(auto=True, margin=self.M)
        self.add_page()

        status_colour = _STATUS_COLOUR.get(section.status, _ACCENT_BLUE)
        status_label  = _STATUS_LABEL.get(section.status, "")

        self._cover_header(
            title    = f"MRI ANALYSIS — {section.section_title.upper()}",
            subtitle = f"Status: {status_label}   |   AI-assisted analysis — mandatory radiologist review",
            generated_at = generated_at,
        )

        if laterality:
            self.set_x(self.M)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*_TEXT_LABEL)
            self.cell(self.epw, 5, f"LATERALITY (DICOM): {laterality.upper()} KNEE", ln=True)
            self.ln(2)

        # Context box — height is dynamic; left bar is drawn after we know it
        self._section_header("CLINICAL CONTEXT")
        x, y = self.M, self.get_y()
        ctx  = _clean(patient_context)
        self.set_xy(x + 6, y + 3)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_TEXT_PRIMARY)
        self.multi_cell(self.epw - 10, 5, ctx)
        ctx_bottom = self.get_y()
        bar_h = ctx_bottom - y + 3
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(x, y, 3, bar_h, "F")
        self.set_y(ctx_bottom)
        self.ln(4)

        # Findings
        self._section_header("DETAILED FINDINGS")
        for sub in section.subsections:
            self._render_subsection(sub)

        # Reasoning
        if section.reasoning:
            self._render_reasoning(section.reasoning)

        # Notes
        if section.notes:
            self._render_notes(section.notes)

        # Images
        if section.images_used:
            self._render_images(section.images_used)

        self._legal_footer()

    def _render_subsection(self, sub: SubsectionFinding) -> None:
        x        = self.M + 6
        bullet_w = 5
        text_indent = x + bullet_w

        self.set_x(x)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*_ACCENT_BLUE)
        self.multi_cell(self.epw - 8, 5, _clean(sub.title))
        self.ln(1)

        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_TEXT_PRIMARY)
        for finding in sub.findings:
            # Inline bullet — no separate cell() before multi_cell so page
            # breaks can't strand the dash on the previous page.
            self.set_x(x + 2)
            self.multi_cell(self.epw - bullet_w - 10, 5, f"-  {_clean(finding)}")
        self.ln(2)

    def _render_reasoning(self, reasoning: str) -> None:
        x       = self.M + 6
        pad     = 4
        inner_w = self.epw - 8 - pad * 2
        self.set_font("Helvetica", "I", 8.5)
        lines   = self._count_lines(_clean(reasoning), inner_w, 5)
        block_h = 5 + lines * 5 + pad
        # Ensure the whole block fits on the current page
        if self.get_y() + block_h > self.h - self.b_margin:
            self.add_page()
        y = self.get_y()
        self.set_fill_color(38, 38, 55)
        self.rect(x, y, self.epw - 8, block_h, "F")
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(x, y, 2, block_h, "F")
        self.set_xy(x + pad + 2, y + 3)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*_ACCENT_BLUE)
        self.cell(inner_w, 4, "REASONING", ln=True)
        self.set_x(x + pad + 2)
        self.set_font("Helvetica", "I", 8.5)
        self.set_text_color(*_TEXT_SECONDARY)
        self.multi_cell(inner_w, 5, _clean(reasoning), fill=False)
        # Use whichever is further down — never rewind the cursor
        self.set_y(max(self.get_y(), y + block_h) + 2)

    def _render_notes(self, notes: list[str]) -> None:
        x       = self.M + 6
        pad     = 4
        inner_w = self.epw - 8 - pad * 2 - 5
        total_lines = sum(self._count_lines(_clean(n), inner_w, 5) for n in notes)
        block_h = 5 + total_lines * 5 + len(notes) * 2 + pad
        # Ensure the whole block fits on the current page
        if self.get_y() + block_h > self.h - self.b_margin:
            self.add_page()
        y = self.get_y()
        self.set_fill_color(28, 28, 42)
        self.rect(x, y, self.epw - 8, block_h, "F")
        self.set_fill_color(*_TEXT_LABEL)
        self.rect(x, y, 2, block_h, "F")
        self.set_xy(x + pad + 2, y + 3)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*_TEXT_LABEL)
        self.cell(inner_w, 4, "OBSERVATIONS", ln=True)
        self.set_font("Helvetica", "I", 8.5)
        self.set_text_color(*_TEXT_SECONDARY)
        for note in notes:
            # Inline bullet — avoids page-break orphan
            self.set_x(x + pad + 2)
            self.multi_cell(inner_w, 5, f"-  {_clean(note)}", fill=False)
            self.ln(1)
        # Use whichever is further down — never rewind the cursor
        self.set_y(max(self.get_y(), y + block_h) + 2)

    def _render_images(self, image_paths: list[str]) -> None:
        self._section_header("REPRESENTATIVE IMAGES")
        valid = [Path(p) for p in image_paths[:3] if Path(p).exists()]
        if not valid:
            self.set_x(self.M)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*_TEXT_LABEL)
            self.cell(self.epw, 6, "Image paths not found on disk.", ln=True)
            return

        gap   = 3
        pad   = 2
        n     = len(valid)
        slots = 3
        img_w = (self.epw - pad * 2 - gap * (slots - 1)) / slots
        img_h = 46
        strip_y = self.get_y() + 3
        actual_w = n * img_w + (n - 1) * gap
        x0 = self.M + pad + (self.epw - pad * 2 - actual_w) / 2

        for i, p in enumerate(valid):
            x = x0 + i * (img_w + gap)
            self.set_fill_color(*_WHITE)
            self.rect(x - pad, strip_y - pad, img_w + pad * 2, img_h + pad * 2, "F")
            buf = io.BytesIO(p.read_bytes())
            buf.seek(0)
            self.image(buf, x=x, y=strip_y, w=img_w, h=img_h)
            self.set_draw_color(*_IMG_BORDER)
            self.set_line_width(0.3)
            self.rect(x - pad, strip_y - pad, img_w + pad * 2, img_h + pad * 2, "D")
        self.set_y(strip_y + img_h + pad + 4)


# ---------------------------------------------------------------------------
# Summary PDF
# ---------------------------------------------------------------------------

class _SummaryPDF(_BasePDF):

    def build_summary(
        self,
        synthesis: SynthesisResult,
        sections: list[SectionResult],
        patient_context: str,
        generated_at: datetime,
    ) -> None:
        self.set_margins(self.M, self.M, self.M)
        self.set_auto_page_break(auto=True, margin=self.M)
        self.add_page()

        self._cover_header(
            title    = "MRI SYNTHESIS REPORT",
            subtitle = "AI-assisted integrated analysis — mandatory radiologist review",
            generated_at = generated_at,
        )

        # Section status overview
        self._section_header("SECTION STATUS OVERVIEW")
        col_w = self.epw / 2
        for i, sec in enumerate(sections):
            colour = _STATUS_COLOUR.get(sec.status, _ACCENT_BLUE)
            bg     = _STATUS_BG.get(sec.status, _CARD_BG)
            label  = _STATUS_LABEL.get(sec.status, "")
            row_y  = self.get_y()
            if i % 2 == 0:
                self.set_x(self.M)
            self.set_fill_color(*bg)
            self.rect(self.get_x(), row_y, 14, 7, "F")
            self.set_xy(self.get_x(), row_y)
            self.set_font("Helvetica", "B", 7)
            self.set_text_color(*colour)
            self.cell(14, 7, label[:3].upper(), align="C")
            self.set_fill_color(*_CARD_BG)
            self.rect(self.get_x(), row_y, col_w - 14, 7, "F")
            self.set_font("Helvetica", "", 8.5)
            self.set_text_color(*_TEXT_PRIMARY)
            self.cell(col_w - 14, 7, _clean(sec.section_title))
            if i % 2 == 1:
                self.ln()
        if len(sections) % 2 == 1:
            self.ln()
        self.ln(4)

        # Summary table
        self._section_header("SUMMARY OF FINDINGS")
        self._render_summary_table(synthesis.summary)

        # Clinical answer
        self._section_header("DIRECT ANSWER TO CLINICAL QUESTION")
        self._render_clinical_answer(synthesis.clinical_answer)

        # Flags
        self._section_header("RADIOLOGIST ATTENTION FLAGS")
        for flag in synthesis.flags:
            self.set_x(self.M + 4)
            self.set_fill_color(*_CARD_BG)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_TEXT_PRIMARY)
            self.multi_cell(self.epw - 4, 6, f"  -  {_clean(flag)}", fill=True)
        self.ln(4)

        self._legal_footer()

    def _render_summary_table(self, items: list[SummaryItem]) -> None:
        pill_w = 20
        lbl_w  = 55
        text_w = self.epw - pill_w - lbl_w
        line_h = 5.5

        for idx, item in enumerate(items):
            colour = _STATUS_COLOUR.get(item.status, _ACCENT_BLUE)
            bg     = _STATUS_BG.get(item.status, _CARD_BG)
            self.set_font("Helvetica", "", 9)
            lines = self._count_lines(_clean(item.text), text_w, line_h)
            row_h = max(lines * line_h + 4, 10)
            if self.get_y() + row_h > 272:
                self.add_page()
            row_y = self.get_y()
            alt   = _CARD_BG if idx % 2 == 0 else _CARD_HDR
            self.set_fill_color(*bg)
            self.rect(self.M, row_y, pill_w, row_h, "F")
            self.set_fill_color(*alt)
            self.rect(self.M + pill_w, row_y, lbl_w, row_h, "F")
            self.rect(self.M + pill_w + lbl_w, row_y, text_w, row_h, "F")
            self.set_xy(self.M, row_y + (row_h - 4) / 2 - 1)
            self.set_font("Helvetica", "B", 7.5)
            self.set_text_color(*colour)
            self.cell(pill_w, 4, _STATUS_LABEL.get(item.status, "")[:6].upper(), align="C")
            label_text = _clean(item.label)
            while self.get_string_width(label_text) > lbl_w - 4 and len(label_text) > 3:
                label_text = label_text[:-1]
            if label_text != _clean(item.label):
                label_text = label_text[:-1] + "..."
            self.set_xy(self.M + pill_w + 2, row_y + (row_h - 4) / 2 - 1)
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*_TEXT_PRIMARY)
            self.cell(lbl_w - 2, 4, label_text)
            self.set_xy(self.M + pill_w + lbl_w + 3, row_y + 2)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_TEXT_SECONDARY)
            self.multi_cell(text_w - 6, line_h, _clean(item.text))
            self.set_y(row_y + row_h)
        self.ln(4)

    def _render_clinical_answer(self, answer) -> None:
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
            self.set_font("Helvetica", "", 9)
            lines = self._count_lines(_clean(value), val_w, line_h)
            row_h = max(lines * line_h + 4, 10)
            if self.get_y() + row_h > 272:
                self.add_page()
            row_y = self.get_y()
            lbl_c = _CARD_HDR if idx % 2 == 0 else (35, 35, 50)
            self.set_fill_color(*lbl_c)
            self.rect(self.M, row_y, lbl_w, row_h, "F")
            val_c = _CARD_BG if idx % 2 == 0 else (26, 26, 38)
            self.set_fill_color(*val_c)
            self.rect(self.M + lbl_w, row_y, val_w, row_h, "F")
            self.set_xy(self.M + 3, row_y + (row_h - 4) / 2 - 1)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*_TEXT_LABEL)
            self.cell(lbl_w - 3, 4, label)
            self.set_xy(self.M + lbl_w + 3, row_y + 2)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_TEXT_PRIMARY)
            self.multi_cell(val_w - 6, line_h, _clean(value))
            self.set_y(row_y + row_h)
        self.ln(4)
