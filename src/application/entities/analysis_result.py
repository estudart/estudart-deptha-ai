from typing import Literal

from pydantic import BaseModel, Field


class Subsection(BaseModel):
    title: str = Field(description="Anatomical sub-structure being described (e.g. 'ACL / ACL Graft').")
    findings: list[str] = Field(description="List of specific image observations for this sub-structure.")


class Section(BaseModel):
    title: str = Field(description="Anatomical section name (e.g. 'Ligaments', 'Menisci').")
    images_used: list[str] = Field(
        default=[],
        description=(
            "Absolute file paths of the images you fetched and examined for this section, "
            "exactly as returned by get_slices in the 'fetched_filenames' field. "
            "Include every path you actually looked at — these are used by the report builder "
            "to render the images. Order by diagnostic importance (most relevant first). "
            "2-3 paths is ideal."
        ),
    )
    status: Literal["normal", "attention", "significant"] = Field(
        description=(
            "'normal' — no relevant findings in this section. "
            "'attention' — findings present but not expected to alter clinical management; monitor. "
            "'significant' — findings that may alter clinical management and require priority radiologist review."
        ),
    )
    subsections: list[Subsection] = Field(default=[], description="Detailed per-structure findings within this section.")
    reasoning: str | None = Field(
        default=None,
        description=(
            "Brief radiological reasoning behind the assigned status — explain why this section is normal, "
            "requires attention, or is significant. Reference specific image features that drove the conclusion. "
            "2-4 sentences."
        ),
    )
    notes: list[str] = Field(
        default=[],
        description=(
            "Interpretive notes for the radiologist — distinguish expected post-surgical changes "
            "from pathology; state explicitly when failure criteria are NOT met."
        ),
    )


class SummaryItem(BaseModel):
    label: str = Field(description="Short anatomical label (e.g. 'ACL Graft', 'Lateral Meniscus Repair').")
    status: Literal["normal", "attention", "significant"] = Field(
        description=(
            "'normal' — no relevant findings for this structure. "
            "'attention' — findings present but not expected to alter clinical management; monitor. "
            "'significant' — findings that may alter clinical management and require priority radiologist review."
        )
    )
    text: str = Field(description="One-sentence plain-language summary of the finding.")


class ClinicalAnswer(BaseModel):
    question: str = Field(description="Restate the primary clinical question exactly as given in the patient context.")
    answer: str = Field(description="Focused, direct answer based solely on image findings — 2-3 sentences maximum.")
    confidence: Literal["High", "Moderate", "Low"] = Field(
        description="Confidence level: 'High' if findings are clear and unambiguous; 'Moderate' if some uncertainty exists; 'Low' if image quality or coverage limits interpretation."
    )
    limiting_factors: str = Field(
        description="Image quality issues, missing sequences, or coverage gaps that limit interpretation. Use 'None' if no limitations."
    )


class AnalysisResult(BaseModel):
    sections: list[Section] = Field(
        description=(
            "Required sections in this order: "
            "1. Ligaments, 2. Menisci, 3. Articular Cartilage, "
            "4. Subchondral Bone and Bone Marrow, 5. Periarticular Structures, 6. Joint Fluid and Synovium."
        )
    )
    summary: list[SummaryItem] = Field(description="One summary item per key structure assessed.")
    clinical_answer: ClinicalAnswer = Field(description="Direct answer to the primary clinical question.")
    flags: list[str] = Field(
        description=(
            "Findings requiring priority radiologist review — one line each with explanation. "
            "If no flags: use ['No priority flags — findings consistent with expected post-operative changes.']"
        )
    )
