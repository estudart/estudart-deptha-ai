"""
ImageSelector — deterministic per-section image selection.

APPLICATION SERVICE — no LLM dependency.
Lives in src/application/services/, NOT agents/.
agents/ is reserved for components that directly invoke language models.

Each section folder contains images from multiple MRI series.
Rules:
  Full coverage (every slice): ACL/cruciate/oblique dedicated sequences,
                               sagittal PD, sagittal T2.
  Sampled (every 3rd slice):  sagittal T1, coronal, axial sequences.

Hard cap at 99 images per section (Anthropic limit is 100).
Path is embedded in the label so the model can reference it in images_used.
"""

from pathlib import Path

_IMAGE_EXTENSIONS     = {".jpg", ".jpeg", ".png"}
_SAMPLE_STEP          = 3
_MAX_IMAGES_PER_CALL  = 99

_FULL_COVERAGE_KEYWORDS = {"cruzado", "cruciate", "obliq", "lca", "acl"}
_FULL_COVERAGE_SAG      = {"pd", "t2"}   # sag+pd or sag+t2 → full; sag+t1 → sampled


def _needs_full_coverage(series_name: str) -> bool:
    lower = series_name.lower()
    if any(kw in lower for kw in _FULL_COVERAGE_KEYWORDS):
        return True
    if "sag" in lower and any(kw in lower for kw in _FULL_COVERAGE_SAG):
        return True
    return False


def _section_display(folder_name: str) -> str:
    return folder_name.split("_", 1)[-1].replace("_", " ").title()


def _group_by_series(images: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for img in images:
        stem   = img.stem
        marker = "_slice_"
        name   = stem[: stem.rfind(marker)] if marker in stem else stem
        groups.setdefault(name, []).append(img)
    return groups


class ImageSelector:
    """Stateless — safe to use as a singleton."""

    def select_section(self, section_dir: Path) -> list[tuple[Path, str]]:
        """
        Select images from a single section folder.
        Returns [(path, label), ...] — path embedded in label for model reference.
        Label format: "Menisci | sag_pd_fse_fs | slice 12 | /abs/path/file.jpg"
        """
        if not section_dir.is_dir():
            return []

        section_label = _section_display(section_dir.name)
        images        = sorted(f for f in section_dir.iterdir() if f.suffix in _IMAGE_EXTENSIONS)
        series_map    = _group_by_series(images)

        selected: list[tuple[Path, str]] = []
        for series_name, files in series_map.items():
            step = 1 if _needs_full_coverage(series_name) else _SAMPLE_STEP
            for i in range(0, len(files), step):
                path  = files[i]
                label = f"{section_label} | {series_name} | slice {i + 1} | {path}"
                selected.append((path, label))

        return selected[:_MAX_IMAGES_PER_CALL]
