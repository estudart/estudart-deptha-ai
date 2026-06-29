import shutil
import tempfile
from pathlib import Path

from src.application.entities.series_summary import SeriesSummary

from src.domain.models.report import Report
from src.infrastructure.dicom_reader import DicomReader
from src.infrastructure.image_encoder import ImageEncoder
from src.infrastructure.openai_client import OpenAIClient

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_DEFAULT_PROMPT = _PROMPTS_DIR / "prompt_knee.md"


class AnalysisService:
    def __init__(
        self,
        dicom_reader: DicomReader,
        image_encoder: ImageEncoder,
        openai_client: OpenAIClient,
    ) -> None:
        self._dicom_reader = dicom_reader
        self._image_encoder = image_encoder
        self._openai_client = openai_client

    def run(
        self,
        input_path: Path,
        patient_context: str,
        prompt_path: Path | None = _DEFAULT_PROMPT,
        slices_per_series: int = 20,
    ) -> Report:
        tmp_dir = None

        try:
            dicom_dir, tmp_dir = self._resolve_input(input_path)

            all_series = self._dicom_reader.load_series(dicom_dir)
            metadata = self._dicom_reader.series_metadata(all_series)

            selected = {
                label: self._dicom_reader.select_slices(
                    slices,
                    slices_per_series
                )
                for label, slices in all_series.items()
                if self._dicom_reader.is_relevant(label)
            }

            images = self._image_encoder.encode_series(selected)
            analysis = self._openai_client.call_vision(
                images,
                patient_context,
                prompt_path
            )

            summaries = [
                SeriesSummary(
                    label=m["label"],
                    slices_total=m["slices"],
                    slices_analysed=len(selected.get(m["label"], [])),
                    modality=m["modality"],
                )
                for m in metadata
            ]

            return Report(
                patient_context=patient_context,
                series_summaries=summaries,
                analysis=analysis,
                encoded_images=images,
            )

        finally:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir)

    def _resolve_input(self, input_path: Path) -> tuple[Path, Path | None]:
        if input_path.suffix.lower() == ".zip":
            tmp = Path(tempfile.mkdtemp(prefix="deptha_"))
            return self._dicom_reader.extract_zip(input_path, tmp), tmp
        return input_path, None
