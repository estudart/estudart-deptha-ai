"""
AnalysisService — orchestrates the full MRI analysis pipeline.

Pipeline:
  1. Classify patient profile → select starter prompt.
  2. Organise exam into section folders.
  3. Analyse each section in parallel (ThreadPoolExecutor) via SectionAnalyser.
  4. Synthesise all section results into a final integrated report (SynthesisAnalyser).
  5. Produce ExamReport with per-section PDFs + summary PDF.

No images leave the service — only structured text and file paths cross boundaries.
"""

import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.application.agents.section_analyser import SectionAnalyser
from src.application.agents.synthesis_analyser import SynthesisAnalyser
from src.application.entities.section_result import SectionResult
from src.application.services.exam_organiser import ExamOrganiser
from src.domain.models.exam_report import ExamReport
from src.infrastructure.logger import Logger

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "sections"

# Maps section folder slug → section prompt file
_SECTION_PROMPTS: dict[str, Path] = {
    "01_ligaments":            _PROMPTS_DIR / "01_ligaments.md",
    "02_menisci":              _PROMPTS_DIR / "02_menisci.md",
    "03_articular_cartilage":  _PROMPTS_DIR / "03_articular_cartilage.md",
    "04_subchondral_bone":     _PROMPTS_DIR / "04_subchondral_bone.md",
    "05_extensor_mechanism":   _PROMPTS_DIR / "05_extensor_mechanism.md",
    "06_joint_fluid":          _PROMPTS_DIR / "06_joint_fluid.md",
    "07_patellar_alignment":   _PROMPTS_DIR / "07_patellar_alignment.md",
}

_DEFAULT_CLINICAL_QUESTION = (
    "Based on the MRI findings, is there structural pathology that explains the patient's symptoms "
    "and what is the clinical significance?"
)

_MAX_WORKERS = 4  # concurrent section analyses (API rate-limit friendly)


class AnalysisService:
    def __init__(
        self,
        exam_organiser: ExamOrganiser,
        section_analyser: SectionAnalyser,
        synthesis_analyser: SynthesisAnalyser,
        logger: Logger,
    ) -> None:
        self._exam_organiser     = exam_organiser
        self._section_analyser   = section_analyser
        self._synthesis_analyser = synthesis_analyser
        self._log                = logger

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_input(self, input_path: Path) -> tuple[Path, Path | None]:
        if input_path.suffix.lower() == ".zip":
            tmp = Path(tempfile.mkdtemp(prefix="deptha_"))
            self._log.info("Extracting zip archive", zip=str(input_path), tmp=str(tmp))
            with zipfile.ZipFile(input_path) as zf:
                zf.extractall(tmp)
            return tmp, tmp
        return input_path, None

    def _load_prompt(self, section_slug: str) -> str:
        path = _SECTION_PROMPTS.get(section_slug)
        if path and path.exists():
            return path.read_text(encoding="utf-8")
        self._log.warning("Section prompt not found — using generic prompt", section=section_slug)
        return (
            f"You are analysing the {section_slug.replace('_', ' ').title()} section of a knee MRI. "
            "Assess all visible structures. Classify each finding by severity. "
            "Provide detailed radiological observations and reasoning."
        )

    def _analyse_section(
        self,
        section_dir: Path,
        patient_context: str,
        output_language: str,
        laterality: str | None,
    ) -> SectionResult:
        section_slug   = section_dir.name
        section_prompt = self._load_prompt(section_slug)
        return self._section_analyser.analyse(
            section_dir     = section_dir,
            section_prompt  = section_prompt,
            patient_context = patient_context,
            output_language = output_language,
            laterality      = laterality,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        input_path: Path,
        patient_context: str,
        output_language: str = "English",
        clinical_question: str = _DEFAULT_CLINICAL_QUESTION,
    ) -> ExamReport:
        tmp_dir = None
        try:
            self._log.info("Pipeline started", input=str(input_path))

            exam_dir, tmp_dir = self._resolve_input(input_path)

            # Stage 1 — organise into section folders
            organised = self._exam_organiser.organise(exam_dir)
            organised_dir = organised.organised_dir
            laterality    = organised.laterality

            self._log.info("Exam organised", laterality=laterality, sections=len(_SECTION_PROMPTS))

            # Stage 2 — discover section folders that have images
            section_dirs = sorted(
                d for d in organised_dir.iterdir()
                if d.is_dir() and any(d.iterdir())
            )
            self._log.info("Sections with images", count=len(section_dirs))

            # Stage 3 — parallel section analysis
            section_results: list[SectionResult] = []
            failed: list[str] = []

            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                futures = {
                    pool.submit(
                        self._analyse_section,
                        sec_dir,
                        patient_context,
                        output_language,
                        laterality,
                    ): sec_dir.name
                    for sec_dir in section_dirs
                }
                for future in as_completed(futures):
                    sec_name = futures[future]
                    try:
                        result = future.result()
                        section_results.append(result)
                        self._log.info(
                            "Section complete",
                            section=sec_name,
                            status=result.status,
                        )
                    except Exception as exc:
                        self._log.error("Section failed", section=sec_name, error=str(exc))
                        failed.append(sec_name)

            # Sort by folder name so output order is deterministic
            section_results.sort(key=lambda r: r.section_folder)

            if not section_results:
                raise RuntimeError("All section analyses failed — cannot produce report.")

            if failed:
                self._log.warning("Some sections failed", failed=failed)

            # Stage 4 — synthesis (text only, no images)
            synthesis = self._synthesis_analyser.synthesise(
                sections          = section_results,
                patient_context   = patient_context,
                clinical_question = clinical_question,
                output_language   = output_language,
            )

            self._log.info("Synthesis complete", flags=len(synthesis.flags))

            return ExamReport(
                patient_context    = patient_context,
                clinical_question  = clinical_question,
                laterality         = laterality,
                sections           = section_results,
                synthesis          = synthesis,
            )

        except Exception as exc:
            self._log.error("Pipeline failed", error=str(exc))
            raise

        finally:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir)
                self._log.info("Temp directory cleaned up", path=str(tmp_dir))
