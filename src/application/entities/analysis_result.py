from typing import Literal

from pydantic import BaseModel


class Subsection(BaseModel):
    title: str
    findings: list[str]


class Section(BaseModel):
    title: str
    series_label: str | None = None
    best_slice_index: int | None = None
    status: Literal["normal", "attention", "significant"]
    subsections: list[Subsection] = []
    notes: list[str] = []


class SummaryItem(BaseModel):
    label: str
    status: Literal["normal", "attention", "significant"]
    text: str


class ClinicalAnswer(BaseModel):
    question: str
    answer: str
    confidence: Literal["High", "Moderate", "Low"]
    limiting_factors: str


class AnalysisResult(BaseModel):
    sections: list[Section]
    summary: list[SummaryItem]
    clinical_answer: ClinicalAnswer
    flags: list[str]
