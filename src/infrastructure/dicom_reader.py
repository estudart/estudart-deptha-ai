import zipfile
from pathlib import Path

import pydicom


class DicomReader:
    SKIP_KEYWORDS = ["localizer", "scout", "loc", "3-plane", "survey"]

    def extract_zip(self, zip_path: Path, target_dir: Path) -> Path:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target_dir)
        return target_dir

    def load_series(self, dicom_dir: Path) -> dict[str, list[tuple[str, pydicom.Dataset]]]:
        """Returns dict[series_label, list[(filename, dataset)]] sorted by InstanceNumber."""
        series: dict[str, list[tuple[str, pydicom.Dataset]]] = {}

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
            series.setdefault(label, []).append((path.name, ds))

        for label in series:
            series[label].sort(key=lambda item: int(getattr(item[1], "InstanceNumber", 0)))

        return series

    def series_metadata(self, series: dict[str, list[tuple[str, pydicom.Dataset]]]) -> list[dict]:
        result = []
        for label, slices in series.items():
            _, ds = slices[0]
            result.append({
                "label": label,
                "slices": len(slices),
                "modality": getattr(ds, "Modality", "?"),
                "rows": getattr(ds, "Rows", "?"),
                "columns": getattr(ds, "Columns", "?"),
            })
        return result

    def extract_laterality(self, series: dict[str, list[tuple[str, pydicom.Dataset]]]) -> str | None:
        for slices in series.values():
            for _, ds in slices[:3]:
                for tag in ("Laterality", "ImageLaterality"):
                    val = str(getattr(ds, tag, "") or "").strip().upper()
                    if val in ("L", "LEFT"):
                        return "Left"
                    if val in ("R", "RIGHT"):
                        return "Right"
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

    def select_slices(
        self,
        slices: list[tuple[str, pydicom.Dataset]],
        n: int,
        label: str = "",
    ) -> list[tuple[str, pydicom.Dataset]]:
        """
        Select n representative slices with center-bias (60% from central third, 40% uniform).
        Key anatomy is almost always in the middle of the acquisition for all planes.
        """
        total = len(slices)
        if total <= n:
            return slices

        if total >= 6:
            c_start = total // 3
            c_end = 2 * total // 3
            central = slices[c_start:c_end + 1]

            n_central = max(1, round(n * 0.60))
            n_uniform = max(1, n - n_central)

            if len(central) <= n_central:
                c_indices: set[int] = {c_start + i for i in range(len(central))}
            else:
                c_indices = {
                    c_start + round(i * (len(central) - 1) / (n_central - 1))
                    for i in range(n_central)
                }

            u_indices = {
                round(i * (total - 1) / (n_uniform - 1))
                for i in range(n_uniform)
            } if n_uniform > 1 else {0}

            chosen = sorted(c_indices | u_indices)
            while len(chosen) > n:
                chosen.pop()
            return [slices[i] for i in chosen]

        indices = {round(i * (total - 1) / (n - 1)) for i in range(n)}
        return [slices[i] for i in sorted(indices)]
