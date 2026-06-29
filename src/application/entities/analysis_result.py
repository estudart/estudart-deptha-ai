from typing import Literal

from pydantic import BaseModel, Field


class Subsection(BaseModel):
    title: str = Field(description="Anatomical sub-structure being described (e.g. 'ACL / ACL Graft').")
    findings: list[str] = Field(description="List of specific image observations for this sub-structure.")


class Section(BaseModel):
    title: str = Field(description="Anatomical section name (e.g. 'Ligaments', 'Menisci').")
    series_label: str | None = Field(
        default=None,
        description=(
            "Exact label of the MRI series that best shows this section's structures, "
            "as it appears in the image list (e.g. 'WATER: COR PD FSE FLEX'). "
            "Prefer sagittal for ligaments/cartilage/bone, coronal for meniscal body/extrusion, axial for synovium."
        ),
    )
    best_slice_index: int | None = Field(
        default=None,
        description=(
            "0-based index of the single slice within the chosen series that most clearly "
            "demonstrates the key finding for this section. Omit if uncertain."
        ),
    )
    status: Literal["normal", "attention", "significant"] = Field(
        description=(
            "'normal' — intact structures, no unexpected signal changes. "
            "'attention' — expected post-surgical changes, mild edema, effusion, or findings to monitor. "
            "'significant' — unexpected pathology that may alter clinical management "
            "(actual tear, graft failure, displaced fragment, fracture)."
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
    status: Literal["normal", "attention", "significant"] = Field(description="Overall status for this structure.")
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
