from typing import Literal

from pydantic import BaseModel, Field


class SummaryItem(BaseModel):
    label: str = Field(description="Short anatomical label (e.g. 'ACL', 'Lateral Meniscus').")
    status: Literal["normal", "attention", "significant"]
    text: str = Field(description="One-sentence plain-language summary of the finding.")


class ClinicalAnswer(BaseModel):
    question: str = Field(description="Primary clinical question restated exactly as given.")
    answer: str   = Field(description="Focused answer based solely on section findings. 2–3 sentences.")
    confidence: Literal["High", "Moderate", "Low"]
    limiting_factors: str = Field(
        description="Coverage gaps, image quality issues, or sequence limitations. 'None' if unrestricted."
    )


class SynthesisResult(BaseModel):
    """
    Final synthesis — produced from all section texts, no images.
    Integrates findings across sections into a clinical impression.
    """

    summary: list[SummaryItem] = Field(
        description="One item per key structure assessed across all sections."
    )
    clinical_answer: ClinicalAnswer = Field(
        description="Direct answer to the primary clinical question."
    )
    flags: list[str] = Field(
        description=(
            "Findings requiring priority radiologist review — one flag per line with explanation. "
            "If nothing urgent: ['No priority flags identified.']"
        )
    )
