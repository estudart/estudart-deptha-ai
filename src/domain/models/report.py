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
    "—": "-", "–": "-",
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    "…": "...",
    "·": "-", "•": "-",
    "→": "->", "✓": "OK",
    "■": "#", "×": "x",
    "\U0001f7e2": "", "\U0001f7e1": "", "\U0001f534": "",
})


def _clean(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = text.translate(_UNICODE_REPLACEMENTS)
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

_BLUE_DARK  = (22,  60, 120)
_BLUE_MID   = (30,  90, 180)
_BLUE_LIGHT = (235, 242, 255)
_GREEN      = (25, 130,  70)
_GREEN_BG   = (232, 248, 238)
_ORANGE     = (200, 110,  15)
_ORANGE_BG  = (255, 248, 235)
_RED        = (180,  35,  35)
_RED_BG     = (255, 235, 235)
_DARK       = (25,   25,  25)
_GREY_DARK  = (90,   90,  90)
_GREY_MID   = (160, 160, 160)
_GREY_LIGHT = (245, 245, 245)
_WHITE      = (255, 255, 255)

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
_SUMMARY_ICON: dict[str, str] = {
    "normal":      "OK",
    "attention":   "!!",
    "significant": "!!",
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
            "# Deptha - MRI Report",
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
# PDF renderer
# ---------------------------------------------------------------------------

class _ReportPDF(FPDF):
    M = 18  # page margin

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

        slice_assignments = self._assign_slices(report.analysis.sections, report.encoded_images)
        for i, sec in enumerate(report.analysis.sections):
            self._section_card(sec, slice_assignments.get(i))

        self._summary_section(report.analysis.summary)
        self._clinical_answer(report.analysis.clinical_answer)
        self._flags_section(report.analysis.flags)
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

        self.set_x(self.M)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*_GREY_DARK)
        self.cell(self.epw, 5, "CLINICAL CONTEXT", ln=True)

        ctx = _clean(report.patient_context)
        x, y = self.M, self.get_y()
        self.set_fill_color(*_BLUE_LIGHT)
        self.rect(x, y, self.epw, 1, "F")
        self.set_xy(x + 3, y + 3)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK)
        self.multi_cell(self.epw - 6, 5, ctx, fill=False)
        bottom = self.get_y()
        self.rect(x, y, self.epw, bottom - y + 3, "F")
        self.set_xy(x + 3, y + 3)
        self.multi_cell(self.epw - 6, 5, ctx)
        self.set_y(bottom + 4)

        fields = [
            ("Series analysed", str(len(report.series_summaries))),
            ("Total slices",    str(sum(s.slices_total for s in report.series_summaries))),
            ("Analysis date",   report.generated_at.strftime("%B %d, %Y")),
        ]
        col_lbl = 30
        col_val = (self.epw / len(fields)) - col_lbl

        self.set_x(self.M)
        for label, value in fields:
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
            self.cell(cw[0], 7, _clean(s.label[:56]), border=1, fill=fill)
            self.cell(cw[1], 7, str(s.slices_total),    border=1, fill=fill, align="C")
            self.cell(cw[2], 7, str(s.slices_analysed), border=1, fill=fill, align="C")
            self.cell(cw[3], 7, s.modality,             border=1, fill=fill, align="C")
            self.ln()

        self.ln(5)

    # ------------------------------------------------------------------ section card

    def _assign_slices(self, sections: list[Section], encoded_images: dict[str, list[str]]) -> dict[int, io.BytesIO]:
        from collections import defaultdict
        series_to_sections: dict[str, list[int]] = defaultdict(list)
        section_to_series: dict[int, str] = {}

        for i, sec in enumerate(sections):
            key = self._match_series(sec, encoded_images)
            if key:
                series_to_sections[key].append(i)
                section_to_series[i] = key

        assignments: dict[int, io.BytesIO] = {}
        for key, indices in series_to_sections.items():
            slices = encoded_images[key]
            n = len(indices)
            for j, sec_idx in enumerate(indices):
                # Spread evenly through the slice stack: 1/(n+1), 2/(n+1), ...
                slice_idx = int((j + 1) / (n + 1) * len(slices))
                assignments[sec_idx] = io.BytesIO(base64.b64decode(slices[slice_idx]))

        return assignments

    def _section_card(self, section: Section, img_buf: io.BytesIO | None) -> None:
        colour = _STATUS_COLOUR.get(section.status, _BLUE_MID)
        bg     = _STATUS_BG.get(section.status, _BLUE_LIGHT)
        label    = _STATUS_LABEL.get(section.status, "See findings")
        img_size = 44

        text_w = self.epw - (img_size + 5 if img_buf else 0)

        # Page break guard
        if self.get_y() + (img_size + 6 if img_buf else 20) > 272:
            self.add_page()

        start_page = self.page
        y_start    = self.get_y()

        # Card header
        self.set_fill_color(*bg)
        self.rect(self.M, y_start, text_w, 10, "F")
        self.set_xy(self.M + 5, y_start + 1)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_BLUE_DARK)
        self.cell(text_w - 52, 8, _clean(section.title))
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*colour)
        self.cell(47, 8, label, align="R", ln=True)
        self.ln(2)

        # Sub-sections
        for sub in section.subsections:
            self._render_subsection(sub, text_w)

        # Notes (blockquote callouts)
        for note in section.notes:
            self._render_note(note, text_w)

        y_end = self.get_y() + 2

        # Image (same page only)
        if img_buf and self.page == start_page:
            img_x = self.M + text_w + 3
            img_y = y_start + max(0, (y_end - y_start - img_size) / 2)
            if img_y + img_size > 272:
                img_y = y_start
            self.image(img_buf, x=img_x, y=img_y, w=img_size, h=img_size)
            y_end = max(y_end, img_y + img_size + 2)

        # Left accent bar
        if self.page == start_page:
            self.set_fill_color(*colour)
            self.rect(self.M, y_start, 3, y_end - y_start, "F")

        self.set_y(y_end)
        self.ln(5)

    def _render_subsection(self, sub, text_w: float) -> None:
        x = self.M + 5

        # Sub-section title
        self.set_x(x)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*_BLUE_DARK)
        self.multi_cell(text_w - 8, 5, _clean(sub.title))
        self.ln(1)

        # Findings
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK)
        for finding in sub.findings:
            self.set_x(x + 2)
            self.multi_cell(text_w - 10, 5, f"  -  {_clean(finding)}")

        self.ln(2)

    def _render_note(self, note: str, text_w: float) -> None:
        x = self.M + 5
        self.set_x(x + 4)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(*_GREY_DARK)
        self.set_fill_color(*_GREY_LIGHT)
        self.multi_cell(text_w - 12, 5, _clean(note), fill=True)
        self.ln(1)

    # ------------------------------------------------------------------ summary

    def _summary_section(self, items: list[SummaryItem]) -> None:
        self._section_header("4. SUMMARY OF FINDINGS")

        for item in items:
            colour = _STATUS_COLOUR.get(item.status, _BLUE_MID)
            bg     = _STATUS_BG.get(item.status, _BLUE_LIGHT)

            self.set_x(self.M)
            self.set_fill_color(*bg)
            # Status pill
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*colour)
            self.cell(22, 7, _STATUS_LABEL[item.status][:6].upper(), border=0, fill=True, align="C")
            # Label
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(*_DARK)
            self.cell(48, 7, _clean(item.label))
            # Text
            self.set_font("Helvetica", "", 9)
            self.multi_cell(self.epw - 70, 7, _clean(item.text))

        self.ln(4)

    # ------------------------------------------------------------------ clinical answer

    def _clinical_answer(self, answer) -> None:
        self._section_header("5. DIRECT ANSWER TO CLINICAL QUESTION")

        x = self.M
        self.set_fill_color(*_BLUE_LIGHT)
        y = self.get_y()

        rows = [
            ("Clinical question", answer.question),
            ("Image-based answer", answer.answer),
            ("Confidence",         answer.confidence),
            ("Limiting factors",   answer.limiting_factors),
        ]
        lbl_w = 38

        for label, value in rows:
            self.set_x(x)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*_GREY_DARK)
            self.set_fill_color(*_GREY_LIGHT)
            row_y = self.get_y()

            # Measure value height
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_DARK)

            # Draw label cell background
            self.set_fill_color(*_GREY_LIGHT)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*_GREY_DARK)
            self.cell(lbl_w, 7, label, border=1, fill=True)

            # Value
            self.set_fill_color(*_WHITE)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_DARK)
            self.multi_cell(self.epw - lbl_w, 7, _clean(value), border=1, fill=True)

        self.ln(4)

    # ------------------------------------------------------------------ flags

    def _flags_section(self, flags: list[str]) -> None:
        self._section_header("6. RADIOLOGIST ATTENTION FLAGS")

        for flag in flags:
            self.set_x(self.M + 4)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*_DARK)
            self.multi_cell(self.epw - 4, 6, f"  -  {_clean(flag)}")

        self.ln(4)

    # ------------------------------------------------------------------ helpers

    def _match_series(self, section: Section, encoded_images: dict[str, list[str]]) -> str | None:
        if not encoded_images:
            return None

        # Model provided an exact label
        if section.series_label:
            match = next(
                (k for k in encoded_images
                 if section.series_label.lower() in k.lower() or k.lower() in section.series_label.lower()),
                None,
            )
            if match:
                return match

        # Keyword fallback
        t = section.title.lower()
        if any(w in t for w in ("ligament", "acl", "pcl", "collateral")):
            pref = ("sag", "cor")
        elif "menisc" in t:
            pref = ("cor", "pd")
        elif "cartilage" in t:
            pref = ("sag", "t2")
        elif any(w in t for w in ("bone", "marrow", "subchondral")):
            pref = ("sag", "t1")
        elif any(w in t for w in ("fluid", "synovium", "effusion")):
            pref = ("axi", "cor")
        elif any(w in t for w in ("periarticular", "tendon", "soft")):
            pref = ("sag", "axi")
        else:
            pref = ()

        labels = list(encoded_images.keys())
        return next((k for p in pref for k in labels if p in k.lower()), labels[0] if labels else None)

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
