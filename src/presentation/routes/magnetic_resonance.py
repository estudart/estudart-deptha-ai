from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, status
from pydantic import BaseModel, Field

from src.presentation.dependencies import get_analysis_service, get_logger

magnetic_resonance_router = APIRouter(
    prefix="/magnetic-resonance",
    tags=["Magnetic Resonance"],
)

_OUTPUT_ROOT = Path("data/output")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AnalyseExamRequest(BaseModel):
    input_path: str = Field(
        ...,
        description="Absolute or relative path to the DICOM exam — either a `.zip` archive or a directory.",
        examples=["data/input/exam.zip"],
    )
    patient_context: str = Field(
        ...,
        description=(
            "Free-text clinical context for the patient. Include surgical history, "
            "post-operative timing, current symptoms, and the primary clinical question "
            "to be answered. The richer the context, the more targeted the analysis."
        ),
        examples=[
            "Post-op ACL reconstruction + lateral meniscal suture, 3 months. "
            "Intermittent joint locking and pain on full extension. Mild effusion on clinical exam."
        ],
    )
    language: str = Field(
        default="English",
        description="Language for the report output. Examples: 'English', 'Portuguese', 'Spanish', 'French'.",
        examples=["English", "Portuguese"],
    )


class AnalyseExamResponse(BaseModel):
    message: str = Field(description="Human-readable status message.")
    output_dir: str = Field(description="Directory where the report files will be written once analysis completes.")


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

def _run_analysis(input_path: str, patient_context: str, output_language: str, output_dir: Path) -> None:
    log = get_logger()
    service = get_analysis_service()
    report = service.run(
        input_path=Path(input_path),
        patient_context=patient_context,
        output_language=output_language,
    )
    report.save_to_dir(output_dir)
    log.info("Report saved", md=str(output_dir / "report.md"), pdf=str(output_dir / "report.pdf"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@magnetic_resonance_router.post(
    "/analyse-exam",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AnalyseExamResponse,
    summary="Submit an MRI exam for AI-assisted analysis",
    description=(
        "Accepts a DICOM exam (zip archive or directory path) and a clinical context string, "
        "then queues the full analysis pipeline as a background task.\n\n"
        "The endpoint returns **immediately** with HTTP 202 — the analysis runs asynchronously "
        "via AI vision. Once complete, a structured report is written to the `output_dir` "
        "returned in the response, containing:\n\n"
        "- `report.md` — full Markdown report\n"
        "- `report.pdf` — formatted PDF with findings cards and embedded imaging evidence\n\n"
        "> **Note:** This output is AI-assisted and must be reviewed by a licensed radiologist "
        "before any clinical decision is made."
    ),
)
def analyse_exam(body: AnalyseExamRequest, background_tasks: BackgroundTasks) -> AnalyseExamResponse:
    output_dir = _OUTPUT_ROOT / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    get_logger().info(
        "Analysis request accepted",
        input=body.input_path,
        output_dir=str(output_dir),
    )

    background_tasks.add_task(
        _run_analysis,
        body.input_path,
        body.patient_context,
        body.language,
        output_dir,
    )

    return AnalyseExamResponse(
        message="Analysis queued. The report will be written to the output directory once processing completes.",
        output_dir=str(output_dir),
    )
