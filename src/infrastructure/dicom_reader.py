import zipfile
from pathlib import Path

import pydicom


class DicomReader:
    SKIP_KEYWORDS = ["localizer", "scout", "loc", "3-plane", "survey"]

    def extract_zip(self, zip_path: Path, target_dir: Path) -> Path:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target_dir)
        return target_dir

    def load_series(self, dicom_dir: Path) -> dict[str, list[pydicom.Dataset]]:
        series: dict[str, list[pydicom.Dataset]] = {}

        for path in sorted(dicom_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                ds = pydicom.dcmread(str(path))
            except Exception:
                continue

            if not hasattr(ds, "PixelData"):
                continue

            label = str(
                getattr(ds, "SeriesDescription", None)
                or getattr(ds, "SeriesInstanceUID", "unknown")
            )
            series.setdefault(label, []).append(ds)

        for label in series:
            series[label].sort(key=lambda ds: int(getattr(ds, "InstanceNumber", 0)))

        return series

    def series_metadata(self, series: dict[str, list[pydicom.Dataset]]) -> list[dict]:
        result = []
        for label, slices in series.items():
            ds = slices[0]
            result.append({
                "label": label,
                "slices": len(slices),
                "modality": getattr(ds, "Modality", "?"),
                "rows": getattr(ds, "Rows", "?"),
                "columns": getattr(ds, "Columns", "?"),
            })
        return result

    def extract_laterality(self, series: dict[str, list[pydicom.Dataset]]) -> str | None:
        """
        Extract knee laterality from DICOM metadata tags or series descriptions.
        Returns 'Left', 'Right', or None if not determinable.
        """
        for slices in series.values():
            for ds in slices[:3]:
                # Standard DICOM laterality tags
                for tag in ("Laterality", "ImageLaterality"):
                    val = str(getattr(ds, tag, "") or "").strip().upper()
                    if val in ("L", "LEFT"):
                        return "Left"
                    if val in ("R", "RIGHT"):
                        return "Right"
                # Fall back to series description keywords
                desc = str(getattr(ds, "SeriesDescription", "") or "").lower()
                study = str(getattr(ds, "StudyDescription", "") or "").lower()
                for text in (desc, study):
                    if "esquer" in text or " esq" in text or "left" in text or " le " in text:
                        return "Left"
                    if "direit" in text or " dir" in text or "right" in text or " ri " in text:
                        return "Right"
        return None

    def is_relevant(self, label: str) -> bool:
        lower = label.lower()
        return not any(kw in lower for kw in self.SKIP_KEYWORDS)

    def select_slices(self, slices: list[pydicom.Dataset], n: int) -> list[pydicom.Dataset]:
        if len(slices) <= n:
            return slices
        indices = {round(i * (len(slices) - 1) / (n - 1)) for i in range(n)}
        return [slices[i] for i in sorted(indices)]
