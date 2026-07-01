"""
AnalysisService — orchestrates the full MRI analysis pipeline.

Pipeline:
  1. Resolve section folders from the pre-organised input directory.
  2. Analyse each section in parallel (ThreadPoolExecutor) via SectionAnalyser.
  3. Synthesise all section results into a final integrated report (SynthesisAnalyser).
  4. Return ExamReport.

Input contract:
  input_path must be a pre-organised directory containing section subfolders:
    01_ligaments/  02_menisci/  03_articular_cartilage/ ...
  OR a directory that contains an `organised/` subfolder with the same layout.

No images leave the service — only structured text and file paths cross boundaries.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.application.agents.section_analyser import SectionAnalyser
from src.application.agents.synthesis_analyser import SynthesisAnalyser
from src.application.entities.section_result import SectionResult
from src.infrastructure.logger import Logger

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "sections"

_SECTION_PROMPTS: dict[str, Path] = {
    "01_ligaments":            _PROMPTS_DIR / "ligaments.md",
    "02_menisci":              _PROMPTS_DIR / "menisci.md",
    "03_articular_cartilage":  _PROMPTS_DIR / "articular_cartilage.md",
    "04_subchondral_bone":     _PROMPTS_DIR / "subchondral_bone.md",
    "05_extensor_mechanism":   _PROMPTS_DIR / "extensor_mechanism.md",
    "06_joint_fluid":          _PROMPTS_DIR / "joint_fluid.md",
    "07_patellar_alignment":   _PROMPTS_DIR / "patellar_alignment.md",
}

_DEFAULT_CLINICAL_QUESTION = (
    "Based on the MRI findings, is there structural pathology that explains the patient's symptoms "
    "and what is the clinical significance?"
)

_MAX_WORKERS = 4


class AnalysisService:
    def __init__(
        self,
        section_analyser: SectionAnalyser,
        synthesis_analyser: SynthesisAnalyser,
        logger: Logger,
    ) -> None:
        self._section_analyser   = section_analyser
        self._synthesis_analyser = synthesis_analyser
        self._log                = logger

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_organised_dir(self, input_path: Path) -> Path:
        """
        Accept either:
          - data/input/exam_pos/organised/   (already pointing at section folders)
          - data/input/exam_pos              (contains an `organised/` subfolder)
        """
        organised = input_path / "organised"
        if organised.is_dir():
            self._log.info("Using organised/ subfolder", path=str(organised))
            return organised
        if input_path.is_dir():
            return input_path
        raise ValueError(f"Input path does not exist or is not a directory: {input_path}")

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
    ) -> SectionResult:
        section_slug   = section_dir.name
        section_prompt = self._load_prompt(section_slug)
        return self._section_analyser.analyse(
            section_dir     = section_dir,
            section_prompt  = section_prompt,
            patient_context = patient_context,
            output_language = output_language,
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
    ) -> "ExamReport":
        from src.domain.models.exam_report import ExamReport

        try:
            self._log.info("Pipeline started", input=str(input_path))

            organised_dir = self._resolve_organised_dir(input_path)

            # Discover section folders that contain images
            section_dirs = sorted(
                d for d in organised_dir.iterdir()
                if d.is_dir() and any(
                    f for f in d.iterdir() if f.suffix in {".jpg", ".jpeg", ".png"}
                )
            )
            self._log.info("Sections found", count=len(section_dirs))

            if not section_dirs:
                raise ValueError(
                    f"No section folders with images found in: {organised_dir}\n"
                    "Expected subdirectories named 01_ligaments/, 02_menisci/, etc."
                )

            # Parallel section analysis
            section_results: list[SectionResult] = []
            failed: list[str] = []

            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                futures = {
                    pool.submit(
                        self._analyse_section,
                        sec_dir,
                        patient_context,
                        output_language,
                    ): sec_dir.name
                    for sec_dir in section_dirs
                }
                for future in as_completed(futures):
                    sec_name = futures[future]
                    try:
                        result = future.result()
                        section_results.append(result)
                        self._log.info("Section complete", section=sec_name, status=result.status)
                    except Exception as exc:
                        self._log.error("Section failed", section=sec_name, error=str(exc))
                        failed.append(sec_name)

            section_results.sort(key=lambda r: r.section_folder)

            if not section_results:
                raise RuntimeError("All section analyses failed — cannot produce report.")

            if failed:
                self._log.warning("Some sections failed", failed=failed)

            # Synthesis
            synthesis = self._synthesis_analyser.synthesise(
                sections          = section_results,
                patient_context   = patient_context,
                clinical_question = clinical_question,
                output_language   = output_language,
            )

            self._log.info("Synthesis complete", flags=len(synthesis.flags))

            return ExamReport(
                patient_context   = patient_context,
                clinical_question = clinical_question,
                laterality        = None,
                sections          = section_results,
                synthesis         = synthesis,
            )

        except Exception as exc:
            self._log.error("Pipeline failed", error=str(exc))
            raise
