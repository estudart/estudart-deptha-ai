"""
ExamOrganiser — deterministic pre-processing step.

Reads the DICOMDIR to discover series descriptions, slice counts, laterality,
and modality. Maps each series to anatomical sections via keyword matching, then
copies the JPEG slices into a clean structured folder:

    exam_dir/organised/
        01_ligaments/
            cor_pd_water_slice_001.jpg
            sag_t2_cruzado_slice_006.jpg
            ...
        02_menisci/
            cor_pd_water_slice_001.jpg   ← same file, copied per relevant section
            sag_pd_slice_010.jpg
        ...

Returns an OrganisedExam with the organised path + metadata extracted from DICOMDIR.
No DICOM pixel data is ever read — only the DICOMDIR index file.

Future migration: move the organise() call to the upload/unzip pipeline in the cloud
handler. The AnalysisService call becomes a no-op (idempotent skip) instantly.
"""

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pydicom

from src.infrastructure.logger import Logger

# ---------------------------------------------------------------------------
# Section registry — order matters (display order in report)
# ---------------------------------------------------------------------------

_SECTIONS: list[tuple[str, str, list]] = [
    # (folder_slug, display_name, label_patterns)
    ("01_ligaments",           "Ligaments",               [["cor", "water"], ["cor", "pd"], "cruzado", "cruciate", "t2"]),
    ("02_menisci",             "Menisci",                  [["sag", "pd"], ["sag", "t2"], ["cor", "pd"], ["cor", "water"]]),
    ("03_articular_cartilage", "Articular Cartilage",      [["sag", "pd"], ["cor", "pd"], ["cor", "water"]]),
    ("04_subchondral_bone",    "Subchondral Bone",          [["sag", "t1"], ["sag", "pd"], ["sag", "t2"]]),
    ("05_extensor_mechanism",  "Extensor Mechanism",        ["axi"]),
    ("06_joint_fluid",         "Joint Fluid and Synovium",  ["axi"]),
    ("07_patellar_alignment",  "Patellar Alignment",        ["axi"]),
]


@dataclass
class OrganisedExam:
    organised_dir:   Path
    laterality:      str | None
    series_metadata: list[dict] = field(default_factory=list)
    # [{label, slices, modality}] — sourced from DICOMDIR, no pixel reads


def _matches(label: str, patterns: list) -> bool:
    lower = label.lower()
    for p in patterns:
        if isinstance(p, str) and p in lower:
            return True
        if isinstance(p, list) and all(kw in lower for kw in p):
            return True
    return False


def _slug(series_description: str) -> str:
    """Human-readable, filesystem-safe slug from a series description."""
    s = series_description.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:40]


def _extract_laterality(study_desc: str, series_descs: list[str]) -> str | None:
    """Infer Left / Right from free-text study or series descriptions."""
    for text in [study_desc] + series_descs:
        lower = text.lower()
        if any(kw in lower for kw in ("esquerdo", "esquer", " esq", "left")):
            return "Left"
        if any(kw in lower for kw in ("direito", "direit", " dir", "right")):
            return "Right"
    return None


class ExamOrganiser:
    """Stateless — safe to use as a singleton."""

    def __init__(self, logger: Logger) -> None:
        self._log = logger

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_dicomdir(self, exam_dir: Path) -> Path:
        candidate = exam_dir / "DICOMDIR"
        if candidate.exists():
            return candidate
        for child in exam_dir.iterdir():
            deep = child / "DICOMDIR"
            if deep.exists():
                return deep
        raise FileNotFoundError(f"DICOMDIR not found under {exam_dir}")

    def _parse_dicomdir(self, exam_dir: Path) -> tuple[str | None, list[tuple[str, int, str]]]:
        """
        Returns:
            laterality      — 'Left' | 'Right' | None
            series_info     — [(description, slice_count, modality), ...] in DICOMDIR order
        """
        ds = pydicom.dcmread(str(self._find_dicomdir(exam_dir)))

        study_desc = ""
        series_info: list[tuple[str, int, str]] = []

        for record in ds.DirectoryRecordSequence:
            rtype = record.DirectoryRecordType
            if rtype == "STUDY":
                study_desc = str(getattr(record, "StudyDescription", "") or "")
            elif rtype == "SERIES":
                desc     = str(getattr(record, "SeriesDescription", "unknown") or "unknown").strip()
                slices   = int(getattr(record, "NumberOfSeriesRelatedInstances", 0) or 0)
                modality = str(getattr(record, "Modality", "MR") or "MR")
                series_info.append((desc, slices, modality))

        laterality = _extract_laterality(study_desc, [d for d, _, _ in series_info])
        return laterality, series_info

    def _find_jpeg_dir(self, exam_dir: Path) -> Path:
        for jpg in exam_dir.rglob("*.jpg"):
            return jpg.parent
        raise FileNotFoundError(f"No JPEG files found under {exam_dir}")

    def _build_series_map(self, series_info: list[tuple[str, int, str]]) -> dict[str, str]:
        """Map JPEG series key (s0001, s0002 …) → series description."""
        return {f"s{i + 1:04d}": desc for i, (desc, _, _) in enumerate(series_info)}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def organise(self, exam_dir: Path) -> OrganisedExam:
        """
        Organise an exam directory into section-structured JPEG folders.
        Idempotent — skips copy step if organised/ already exists and is populated.
        Always re-reads DICOMDIR metadata (fast, index file only).
        """
        laterality, series_info = self._parse_dicomdir(exam_dir)
        self._log.info(
            "DICOMDIR parsed",
            laterality=laterality or "unknown",
            series=[d for d, _, _ in series_info],
        )

        series_metadata = [
            {"label": desc, "slices": slices, "modality": modality}
            for desc, slices, modality in series_info
        ]

        organised_dir = exam_dir / "organised"

        if organised_dir.exists() and any(organised_dir.iterdir()):
            self._log.info("Exam already organised — skipping copy", path=str(organised_dir))
            return OrganisedExam(organised_dir, laterality, series_metadata)

        self._log.info("Organising exam", exam_dir=str(exam_dir))

        jpeg_dir   = self._find_jpeg_dir(exam_dir)
        series_map = self._build_series_map(series_info)

        # Gather JPEG files grouped and sorted by series + instance
        series_files: dict[str, list[Path]] = {}
        for jpg in sorted(jpeg_dir.glob("image_s*.jpg")):
            parts = jpg.stem.split("_")          # ['image', 's0002', 'i0014']
            if len(parts) < 3:
                continue
            series_files.setdefault(parts[1], []).append(jpg)

        for key in series_files:
            series_files[key].sort(key=lambda p: int(p.stem.split("_")[2][1:]))

        organised_dir.mkdir(parents=True, exist_ok=True)
        total_copied = 0

        for folder_slug, display_name, patterns in _SECTIONS:
            section_dir = organised_dir / folder_slug
            section_dir.mkdir(exist_ok=True)

            for series_key, description in series_map.items():
                if not _matches(description, patterns):
                    continue
                if series_key not in series_files:
                    continue
                file_slug = _slug(description)
                for i, src in enumerate(series_files[series_key], start=1):
                    shutil.copy2(src, section_dir / f"{file_slug}_slice_{i:03d}.jpg")
                    total_copied += 1

            count = sum(1 for _ in section_dir.iterdir())
            self._log.info("Section organised", section=display_name, images=count)

        self._log.info("Organisation complete", total_files_copied=total_copied)
        return OrganisedExam(organised_dir, laterality, series_metadata)
