import shutil
import tempfile
import zipfile
from pathlib import Path

from src.application.agents.mri_analysis_agent import MriAnalysisAgent
from src.application.entities.analysis_result import AnalysisResult
from src.application.entities.series_summary import SeriesSummary
from src.application.services.exam_organiser import ExamOrganiser
from src.domain.models.report import Report
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.logger import Logger

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_PROMPT_REGISTRY: dict[str, Path] = {
    "native_trauma": _PROMPTS_DIR / "prompt_knee_native_trauma.md",
    "post_op":       _PROMPTS_DIR / "prompt_knee_postop.md",
    "degenerative":  _PROMPTS_DIR / "prompt_knee_degenerative.md",
}


class AnalysisService:
    def __init__(
        self,
        llm_client: LLMClient,
        exam_organiser: ExamOrganiser,
        agent: MriAnalysisAgent,
        logger: Logger,
    ) -> None:
        self._llm_client     = llm_client
        self._exam_organiser = exam_organiser
        self._agent          = agent
        self._log            = logger

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_input(self, input_path: Path) -> tuple[Path, Path | None]:
        """Unzip if needed. Returns (exam_dir, tmp_dir_or_None)."""
        if input_path.suffix.lower() == ".zip":
            tmp = Path(tempfile.mkdtemp(prefix="deptha_"))
            self._log.info("Extracting zip archive", zip=str(input_path), tmp=str(tmp))
            with zipfile.ZipFile(input_path) as zf:
                zf.extractall(tmp)
            return tmp, tmp
        return input_path, None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        input_path: Path,
        patient_context: str,
        output_language: str = "English",
    ) -> Report:
        tmp_dir = None

        try:
            self._log.info("Pipeline started", input=str(input_path))

            # Stage 1 — classify patient profile, select prompt
            profile     = self._llm_client.classify_patient(patient_context)
            prompt_path = _PROMPT_REGISTRY.get(profile, _PROMPT_REGISTRY["native_trauma"])
            self._log.info("Patient classified", profile=profile, prompt=prompt_path.name)

            exam_dir, tmp_dir = self._resolve_input(input_path)

            # Stage 2 — organise JPEGs into section folders (idempotent)
            #           also extracts laterality + series metadata from DICOMDIR
            organised = self._exam_organiser.organise(exam_dir)

            # Stage 3 — agent explores organised folder, returns structured analysis
            self._log.info("Agent starting", prompt=prompt_path.name, language=output_language)
            raw, images_used = self._agent.run(
                organised_dir=organised.organised_dir,
                patient_context=patient_context,
                prompt_path=prompt_path,
                output_language=output_language,
                laterality=organised.laterality,
            )
            analysis = AnalysisResult.model_validate(raw)
            self._log.info(
                "Agent complete",
                sections=len(analysis.sections),
                sections_with_images=sum(1 for s in analysis.sections if s.images_used),
            )

            summaries = [
                SeriesSummary(
                    label=m["label"],
                    slices_total=m["slices"],
                    slices_analysed=sum(
                        1 for sec in images_used.values()
                        for p in sec if not p.endswith(":b64")
                    ),
                    modality=m["modality"],
                )
                for m in organised.series_metadata
            ]

            self._log.info("Pipeline complete", series_in_report=len(summaries))

            return Report(
                patient_context=patient_context,
                series_summaries=summaries,
                analysis=analysis,
                image_paths=images_used,
            )

        except Exception as exc:
            self._log.error("Pipeline failed", error=str(exc))
            raise

        finally:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir)
                self._log.info("Temp directory cleaned up", path=str(tmp_dir))
