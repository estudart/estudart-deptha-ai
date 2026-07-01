"""
Agent tools — section-based image exploration over the organised exam folder.

Split in two concerns:
  - SCHEMAS  (static)  — tool signatures bound to the model once at construction.
  - DISPATCH (per-run) — stateful closures created per run() call that do the
                         actual work with organised_dir and images_used.

This avoids calling bind_tools() on every request.
"""

import base64
import json
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from src.infrastructure.logger import Logger

_MAX_IMAGES_PER_CALL = 10
_IMAGE_EXTENSIONS    = {".jpg", ".jpeg", ".png"}
_MIME_TYPES: dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
}


# ---------------------------------------------------------------------------
# Static schemas — bound to the model once at MriAnalysisAgent construction
# ---------------------------------------------------------------------------

@tool
def list_sections() -> str:
    """
    List all anatomical sections available in this exam.
    Returns a JSON array of objects, each with:
      - section: folder name to pass to get_images
      - display_name: human-readable name
      - image_count: total images in the section
      - series: list of {name, start_index, end_index, count} — the individual
                MRI series within this section, sorted alphabetically.
                Use these index ranges to target specific sequences when calling
                get_images (e.g. fetch sagittal PD slices by their index range,
                not the middle of the entire section).
    Always call this first to understand what is available before fetching images.
    """
    return "{}"   # stub — real execution via dispatch()


@tool
def get_images(
    section: Annotated[str, "Exact section folder name from list_sections (e.g. '01_ligaments')."],
    indices: Annotated[
        list[int],
        (
            f"0-based image indices to fetch (0 = first slice, image_count-1 = last). "
            f"Max {_MAX_IMAGES_PER_CALL} per call. "
            "Use the series index ranges from list_sections to target the right sequence — "
            "e.g. sagittal PD/FS for menisci, coronal water for ligaments. "
            "Do NOT blindly pick the middle of the entire section. "
            "Call again with different indices for additional coverage."
        ),
    ],
) -> str:
    """
    Fetch specific images from an anatomical section.
    Images are injected into the conversation right after this tool result.
    Returns the absolute file paths — include them in images_used in your final JSON.
    """
    return "{}"   # stub — real execution via dispatch()


TOOL_SCHEMAS: list = [list_sections, get_images]


# ---------------------------------------------------------------------------
# Per-run dispatch — created fresh each run() with live state
# ---------------------------------------------------------------------------

def _section_display_name(folder_name: str) -> str:
    """'01_ligaments' → 'Ligaments'"""
    return folder_name.split("_", 1)[-1].replace("_", " ").title()


def _load_image_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def make_dispatch(
    organised_dir: Path,
    images_used: dict,      # mutated in place — {section: {file_path: file_path}}
    logger: Logger,
) -> dict[str, callable]:
    """
    Returns {tool_name: callable} with closures over this run's state.
    Called once per run(), not once per tool call.
    """

    def _list_sections(_args: dict) -> str:
        sections = []
        for folder in sorted(organised_dir.iterdir()):
            if not folder.is_dir():
                continue
            images = sorted(f for f in folder.iterdir() if f.suffix in _IMAGE_EXTENSIONS)

            # Build per-series index ranges so the agent can target specific sequences.
            # Files are named  <series_slug>_slice_NNN.ext — group by the slug prefix
            # (everything before "_slice_").
            series_map: dict[str, list[int]] = {}
            for global_idx, img in enumerate(images):
                stem = img.stem  # e.g. "mr_pd_tse_fs_sag_slice_012"
                marker = "_slice_"
                if marker in stem:
                    series_name = stem[: stem.rfind(marker)]
                else:
                    series_name = stem  # fallback: whole stem
                series_map.setdefault(series_name, []).append(global_idx)

            series_info = [
                {
                    "name":        name,
                    "start_index": idxs[0],
                    "end_index":   idxs[-1],
                    "count":       len(idxs),
                }
                for name, idxs in series_map.items()
            ]

            sections.append({
                "section":      folder.name,
                "display_name": _section_display_name(folder.name),
                "image_count":  len(images),
                "series":       series_info,
            })
        logger.info("list_sections", count=len(sections))
        return json.dumps(sections)

    def _get_images(args: dict) -> str:
        section = args.get("section", "")
        indices = args.get("indices", [])[:_MAX_IMAGES_PER_CALL]

        section_dir = organised_dir / section
        if not section_dir.exists():
            logger.warning("get_images — section not found", section=section)
            return json.dumps({"error": f"Section '{section}' not found. Call list_sections."})

        files = sorted(f for f in section_dir.iterdir() if f.suffix in _IMAGE_EXTENSIONS)
        fetched: list[str] = []

        for idx in indices:
            if not (0 <= idx < len(files)):
                continue
            path     = files[idx]
            path_str = str(path)
            b64      = _load_image_b64(path)
            mime     = _MIME_TYPES.get(path.suffix.lower(), "image/jpeg")

            bucket = images_used.setdefault(section, {})
            bucket[path_str]              = path_str   # path tracked permanently
            bucket[path_str + ":b64"]     = b64        # b64 stored transiently, popped after inject
            bucket[path_str + ":mime"]    = mime       # mime type stored transiently, popped after inject

            fetched.append(path_str)

        logger.info("get_images", section=section, requested=len(indices), fetched=len(fetched))
        return json.dumps({
            "section":       section,
            "fetched_paths": fetched,
            "note": "Images attached in the next message. Add these paths to images_used in your final JSON.",
        })

    return {
        "list_sections": _list_sections,
        "get_images":    _get_images,
    }
