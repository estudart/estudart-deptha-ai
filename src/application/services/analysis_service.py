import shutil
import tempfile
from pathlib import Path

from src.application.entities.series_summary import SeriesSummary
from src.domain.models.report import Report
from src.infrastructure.dicom_reader import DicomReader
from src.infrastructure.image_encoder import ImageEncoder
from src.infrastructure.logger import Logger
from src.infrastructure.openai_client import OpenAIClient

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_DEFAULT_PROMPT = _PROMPTS_DIR / "prompt_knee.md"


class AnalysisService:
    def __init__(
        self,
        dicom_reader: DicomReader,
        image_encoder: ImageEncoder,
        openai_client: OpenAIClient,
        logger: Logger,
    ) -> None:
        self._dicom_reader = dicom_reader
        self._image_encoder = image_encoder
        self._openai_client = openai_client
        self._log = logger

    def run(
        self,
        input_path: Path,
        patient_context: str,
        prompt_path: Path | None = _DEFAULT_PROMPT,
        slices_per_series: int = 20,
    ) -> Report:
        tmp_dir = None

        try:
            self._log.info("Pipeline started", input=str(input_path), slices_per_series=slices_per_series)

            dicom_dir, tmp_dir = self._resolve_input(input_path)
            self._log.info("Input resolved", dicom_dir=str(dicom_dir))

            all_series = self._dicom_reader.load_series(dicom_dir)
            self._log.info("DICOM series loaded", total_series=len(all_series))
            for label, slices in all_series.items():
                self._log.info("  series found", label=label, slices=len(slices))

            metadata = self._dicom_reader.series_metadata(all_series)

            selected = {
                label: self._dicom_reader.select_slices(slices, slices_per_series)
                for label, slices in all_series.items()
                if self._dicom_reader.is_relevant(label)
            }

            skipped = set(all_series) - set(selected)
            self._log.info(
                "Series filtered",
                relevant=len(selected),
                skipped=len(skipped),
                skipped_labels=", ".join(skipped) or "none",
            )
            for label, slices in selected.items():
                self._log.info("  selected", label=label, slices_sampled=len(slices))

            self._log.info("Encoding slices to base64 PNG")
            images = self._image_encoder.encode_series(selected)
            total_images = sum(len(v) for v in images.values())
            self._log.info("Encoding complete", total_images_encoded=total_images)

            self._log.info("Sending request to GPT-4o vision", prompt=str(prompt_path))
            analysis = self._openai_client.call_vision(images, patient_context, prompt_path)
            self._log.info("GPT-4o response received", sections=len(analysis.sections))

            summaries = [
                SeriesSummary(
                    label=m["label"],
                    slices_total=m["slices"],
                    slices_analysed=len(selected.get(m["label"], [])),
                    modality=m["modality"],
                )
                for m in metadata
            ]

            self._log.info("Pipeline complete", series_in_report=len(summaries))

            return Report(
                patient_context=patient_context,
                series_summaries=summaries,
                analysis=analysis,
                encoded_images=images,
            )

        except Exception as exc:
            self._log.error("Pipeline failed", error=str(exc))
            raise

        finally:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir)
                self._log.info("Temp directory cleaned up", path=str(tmp_dir))

    def _resolve_input(self, input_path: Path) -> tuple[Path, Path | None]:
        if input_path.suffix.lower() == ".zip":
            tmp = Path(tempfile.mkdtemp(prefix="deptha_"))
            self._log.info("Extracting zip archive", zip=str(input_path), tmp=str(tmp))
            return self._dicom_reader.extract_zip(input_path, tmp), tmp
        return input_path, None
