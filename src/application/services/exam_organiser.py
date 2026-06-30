"""
ExamOrganiser — deterministic pre-processing step.

Supports two exam formats:

  Format A — DICOMDIR + pre-rendered JPEGs (e.g. exam_pre)
      exam_dir/
          exam/DICOMDIR
          exam/jpeg/image_s0001_i0001.jpg ...

  Format B — native DICOM export, series already in subfolders (e.g. exam_pos)
      exam_dir/
          MR_pd_tse_fs_sag/  ← folder name = series description
              uuid.dcm ...
          MR_Obliq LCA/
              uuid.dcm ...

Both formats produce the same organised/ output:

    exam_dir/organised/
        01_ligaments/
            cor_pd_water_slice_001.jpg
            obliq_lca_slice_006.jpg
        02_menisci/
            sag_pd_slice_010.jpg
        ...

Idempotent — skips copy step if organised/ already exists and is populated.
Future migration: move this call to the upload/unzip pipeline in the cloud handler.
"""

import io
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image

from src.infrastructure.logger import Logger

# ---------------------------------------------------------------------------
# Section registry
# ---------------------------------------------------------------------------

_SECTIONS: list[tuple[str, str, list]] = [
    # (folder_slug, display_name, label_patterns)
    ("01_ligaments",           "Ligaments",               [["cor", "water"], ["cor", "pd"], "cruzado", "cruciate", "lca", "acl", "obliq", "t2"]),
    ("02_menisci",             "Menisci",                  [["sag", "pd"], ["sag", "t2"], ["cor", "pd"], ["cor", "water"]]),
    ("03_articular_cartilage", "Articular Cartilage",      [["sag", "pd"], ["cor", "pd"], ["cor", "water"]]),
    ("04_subchondral_bone",    "Subchondral Bone",          [["sag", "t1"], ["sag", "pd"], ["sag", "t2"]]),
    ("05_extensor_mechanism",  "Extensor Mechanism",        ["axi", "tra"]),
    ("06_joint_fluid",         "Joint Fluid and Synovium",  ["axi", "tra"]),
    ("07_patellar_alignment",  "Patellar Alignment",        ["axi", "tra"]),
]

_DCM_EXTENSIONS = {"", ".dcm", ".ima", ".dicom"}


@dataclass
class OrganisedExam:
    organised_dir:   Path
    laterality:      str | None
    series_metadata: list[dict] = field(default_factory=list)
    # [{label, slices, modality}] — sourced from DICOMDIR or folder scan


def _matches(label: str, patterns: list) -> bool:
    lower = label.lower()
    for p in patterns:
        if isinstance(p, str) and p in lower:
            return True
        if isinstance(p, list) and all(kw in lower for kw in p):
            return True
    return False


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:40]


def _extract_laterality_from_text(*texts: str) -> str | None:
    for text in texts:
        lower = text.lower()
        if any(kw in lower for kw in ("esquerdo", "esquer", " esq", "left")):
            return "Left"
        if any(kw in lower for kw in ("direito", "direit", " dir", "right")):
            return "Right"
    return None


def _render_dcm_to_jpeg_bytes(ds: pydicom.Dataset) -> bytes:
    """Normalise a DICOM pixel array and return JPEG bytes."""
    arr = ds.pixel_array.astype(np.float32)
    arr = arr * float(getattr(ds, "RescaleSlope", 1)) + float(getattr(ds, "RescaleIntercept", 0))
    lo, hi = float(np.percentile(arr, 1)), float(np.percentile(arr, 99))
    arr = np.clip(arr, lo, hi)
    arr = (arr - lo) / (hi - lo) * 255 if hi > lo else np.zeros_like(arr)
    img = Image.fromarray(arr.astype(np.uint8), mode="L").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class ExamOrganiser:
    """Stateless — safe to use as a singleton."""

    def __init__(self, logger: Logger) -> None:
        self._log = logger

    # ------------------------------------------------------------------
    # Format detection
    # ------------------------------------------------------------------

    def _is_format_a(self, exam_dir: Path) -> bool:
        """Format A: has a DICOMDIR somewhere inside."""
        return bool(next(exam_dir.rglob("DICOMDIR"), None))

    # ------------------------------------------------------------------
    # Format A helpers — DICOMDIR + pre-rendered JPEGs
    # ------------------------------------------------------------------

    def _parse_dicomdir(self, exam_dir: Path) -> tuple[str | None, list[tuple[str, int, str]]]:
        dicomdir = next(exam_dir.rglob("DICOMDIR"))
        ds = pydicom.dcmread(str(dicomdir))

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

        laterality = _extract_laterality_from_text(study_desc, *[d for d, _, _ in series_info])
        return laterality, series_info

    def _organise_format_a(self, exam_dir: Path, organised_dir: Path) -> tuple[str | None, list[dict]]:
        laterality, series_info = self._parse_dicomdir(exam_dir)
        self._log.info("Format A — DICOMDIR + JPEG", series=[d for d, _, _ in series_info])

        series_map = {f"s{i + 1:04d}": desc for i, (desc, _, _) in enumerate(series_info)}
        jpeg_dir   = next(exam_dir.rglob("*.jpg")).parent

        series_files: dict[str, list[Path]] = {}
        for jpg in sorted(jpeg_dir.glob("image_s*.jpg")):
            parts = jpg.stem.split("_")
            if len(parts) >= 3:
                series_files.setdefault(parts[1], []).append(jpg)
        for key in series_files:
            series_files[key].sort(key=lambda p: int(p.stem.split("_")[2][1:]))

        total = 0
        for folder_slug, display_name, patterns in _SECTIONS:
            section_dir = organised_dir / folder_slug
            section_dir.mkdir(exist_ok=True)
            for series_key, description in series_map.items():
                if not _matches(description, patterns) or series_key not in series_files:
                    continue
                file_slug = _slug(description)
                for i, src in enumerate(series_files[series_key], start=1):
                    shutil.copy2(src, section_dir / f"{file_slug}_slice_{i:03d}.jpg")
                    total += 1
            count = sum(1 for _ in section_dir.iterdir())
            self._log.info("Section organised", section=display_name, images=count)

        self._log.info("Organisation complete", total_files_copied=total)

        metadata = [{"label": d, "slices": s, "modality": m} for d, s, m in series_info]
        return laterality, metadata

    # ------------------------------------------------------------------
    # Format B helpers — native DICOM export, series = subfolders
    # ------------------------------------------------------------------

    def _scan_format_b(self, exam_dir: Path) -> list[tuple[str, list[Path]]]:
        """Return [(series_description, [dcm_paths, ...]), ...] sorted by folder name."""
        result = []
        for folder in sorted(exam_dir.iterdir()):
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            dcm_files = sorted(
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in _DCM_EXTENSIONS and not p.name.startswith(".")
            )
            if dcm_files:
                result.append((folder.name, dcm_files))
        return result

    def _laterality_from_dcm(self, dcm_path: Path) -> str | None:
        try:
            ds = pydicom.dcmread(str(dcm_path), stop_before_pixels=True)
            for tag in ("Laterality", "ImageLaterality"):
                val = str(getattr(ds, tag, "") or "").strip().upper()
                if val in ("L", "LEFT"):
                    return "Left"
                if val in ("R", "RIGHT"):
                    return "Right"
            lat = _extract_laterality_from_text(
                str(getattr(ds, "StudyDescription", "") or ""),
                str(getattr(ds, "SeriesDescription", "") or ""),
            )
            return lat
        except Exception:
            return None

    def _organise_format_b(self, exam_dir: Path, organised_dir: Path) -> tuple[str | None, list[dict]]:
        series_list = self._scan_format_b(exam_dir)
        self._log.info("Format B — native DICOM folders", series=[s for s, _ in series_list])

        laterality: str | None = None
        metadata: list[dict] = []

        # Render DCMs to JPEG and copy into section folders
        total = 0
        for description, dcm_files in series_list:
            if laterality is None:
                laterality = self._laterality_from_dcm(dcm_files[0])

            # Sort by InstanceNumber
            loaded: list[tuple[int, Path, pydicom.Dataset]] = []
            for p in dcm_files:
                try:
                    ds = pydicom.dcmread(str(p), stop_before_pixels=True)
                    inst = int(getattr(ds, "InstanceNumber", 0) or 0)
                    loaded.append((inst, p, ds))
                except Exception:
                    continue
            loaded.sort(key=lambda x: x[0])

            modality = str(getattr(loaded[0][2], "Modality", "MR")) if loaded else "MR"
            metadata.append({"label": description, "slices": len(loaded), "modality": modality})

            file_slug = _slug(description)
            for folder_slug, display_name, patterns in _SECTIONS:
                if not _matches(description, patterns):
                    continue
                section_dir = organised_dir / folder_slug
                section_dir.mkdir(exist_ok=True)

                for i, (_, dcm_path, _) in enumerate(loaded, start=1):
                    dst = section_dir / f"{file_slug}_slice_{i:03d}.jpg"
                    if dst.exists():
                        continue
                    try:
                        ds_full = pydicom.dcmread(str(dcm_path))
                        jpeg_bytes = _render_dcm_to_jpeg_bytes(ds_full)
                        dst.write_bytes(jpeg_bytes)
                        total += 1
                    except Exception as exc:
                        self._log.warning("Failed to render slice", path=str(dcm_path), error=str(exc))

        for folder_slug, display_name, _ in _SECTIONS:
            count = sum(1 for _ in (organised_dir / folder_slug).iterdir()) if (organised_dir / folder_slug).exists() else 0
            self._log.info("Section organised", section=display_name, images=count)

        self._log.info("Organisation complete", total_files_rendered=total)
        return laterality, metadata

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def organise(self, exam_dir: Path) -> OrganisedExam:
        """
        Organise an exam directory into section-structured JPEG folders.
        Detects format automatically (A = DICOMDIR+JPEG, B = native DICOM folders).
        Idempotent — skips copy/render step if organised/ already exists and is populated.
        Always re-reads metadata (fast header reads only when already organised).
        """
        organised_dir = exam_dir / "organised"

        if organised_dir.exists() and any(organised_dir.iterdir()):
            self._log.info("Exam already organised — re-reading metadata only", path=str(organised_dir))
            if self._is_format_a(exam_dir):
                _, series_info = self._parse_dicomdir(exam_dir)
                laterality     = _extract_laterality_from_text(*[d for d, _, _ in series_info])
                metadata       = [{"label": d, "slices": s, "modality": m} for d, s, m in series_info]
            else:
                series_list = self._scan_format_b(exam_dir)
                laterality  = self._laterality_from_dcm(series_list[0][1][0]) if series_list else None
                metadata    = [{"label": d, "slices": len(f), "modality": "MR"} for d, f in series_list]
            return OrganisedExam(organised_dir, laterality, metadata)

        self._log.info("Organising exam", exam_dir=str(exam_dir))
        organised_dir.mkdir(parents=True, exist_ok=True)

        # Create all section folders upfront
        for folder_slug, _, _ in _SECTIONS:
            (organised_dir / folder_slug).mkdir(exist_ok=True)

        if self._is_format_a(exam_dir):
            laterality, metadata = self._organise_format_a(exam_dir, organised_dir)
        else:
            laterality, metadata = self._organise_format_b(exam_dir, organised_dir)

        return OrganisedExam(organised_dir, laterality, metadata)
