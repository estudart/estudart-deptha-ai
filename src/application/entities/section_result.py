from typing import Literal

from pydantic import BaseModel, Field


class SubsectionFinding(BaseModel):
    title: str = Field(description="Anatomical sub-structure (e.g. 'Anterior Horn', 'ACL Graft').")
    findings: list[str] = Field(description="Specific MRI observations for this sub-structure.")


class SectionResult(BaseModel):
    """Structured output from a single-section vision analysis pass."""

    section_folder: str = Field(description="Folder name e.g. '02_menisci'. Set by the service, not the model.")
    section_title: str  = Field(description="Display name e.g. 'Menisci'.")
    status: Literal["normal", "attention", "significant"] = Field(
        description=(
            "'normal' — no clinically relevant findings. "
            "'attention' — findings present but unlikely to change immediate management. "
            "'significant' — findings that may alter clinical management or require urgent review."
        )
    )
    subsections: list[SubsectionFinding] = Field(
        default=[],
        description="Per-structure breakdown. Each subsection covers one anatomical sub-structure.",
    )
    reasoning: str = Field(
        description=(
            "Radiological reasoning for the assigned status. Reference specific image features, "
            "signal characteristics, and sequences used. 2–4 sentences."
        )
    )
    notes: list[str] = Field(
        default=[],
        description=(
            "Interpretive notes for the radiologist — distinguish expected changes from pathology, "
            "state explicitly when failure or tear criteria are NOT met, flag limitations."
        ),
    )
    images_used: list[str] = Field(
        default=[],
        description=(
            "2–3 absolute file paths of the most diagnostically relevant images examined. "
            "Copy the path exactly from the image label provided in the prompt."
        ),
    )
