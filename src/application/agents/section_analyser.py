"""
SectionAnalyser — agentic single-section vision analysis.

AGENT — directly invokes a language model with tool-calling.

How it works:
  1. The agent receives a directory listing (paths + series metadata) — no pixel data yet.
  2. It calls `view_images` with the paths it wants to examine.
  3. Those images are returned as multimodal content in the tool result.
  4. The agent iterates (view more images if needed) until it is confident.
  5. When done, it outputs a final JSON — no more tool calls.

This gives the model full control over which images to look at, how many,
and in what order — removing the brittle pre-selection heuristics entirely.
"""

import base64
import json
import re
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from src.application.entities.section_result import SectionResult
from src.infrastructure.logger import Logger

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_MIME: dict[str, str] = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

_MAX_IMAGES_PER_CALL = 20   # images the agent may request in one view_images call
_MAX_TOOL_ROUNDS     = 6    # max back-and-forth iterations before forcing output


# ---------------------------------------------------------------------------
# Tool schemas (passed to model via bind_tools / function-calling)
# ---------------------------------------------------------------------------

_LIST_IMAGES_TOOL = {
    "name": "list_images",
    "description": (
        "List all available MRI images in this section folder. "
        "Returns metadata only (path, series name, slice number) — no pixel data. "
        "Call this first to understand what is available before requesting images to view."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_VIEW_IMAGES_TOOL = {
    "name": "view_images",
    "description": (
        "Fetch and view specific MRI images by their file paths. "
        "Pass an array of absolute paths from the list_images output. "
        f"Maximum {_MAX_IMAGES_PER_CALL} images per call. "
        "You may call this tool multiple times to examine different slices or series."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Absolute file paths of the images to view.",
            }
        },
        "required": ["paths"],
    },
}


# ---------------------------------------------------------------------------
# SectionAnalyser
# ---------------------------------------------------------------------------

class SectionAnalyser:
    """Stateless — each analyse() call is fully independent."""

    def __init__(self, model: BaseChatModel, logger: Logger) -> None:
        self._model = model
        self._log   = logger

    # ------------------------------------------------------------------
    # Directory listing (tool: list_images)
    # ------------------------------------------------------------------

    def _list_images(self, section_dir: Path) -> str:
        """Return a plain-text manifest of all images in the section folder."""
        images = sorted(
            f for f in section_dir.iterdir() if f.suffix.lower() in _IMAGE_EXTENSIONS
        )
        if not images:
            return "No images found in this section folder."

        lines = [f"Section folder: {section_dir.name}", f"Total images: {len(images)}", ""]

        # Group by series (stem up to _slice_)
        groups: dict[str, list[Path]] = {}
        for img in images:
            stem = img.stem
            marker = "_slice_"
            series = stem[: stem.rfind(marker)] if marker in stem else stem
            groups.setdefault(series, []).append(img)

        for series, files in groups.items():
            lines.append(f"Series: {series}  ({len(files)} slices)")
            for f in files:
                lines.append(f"  {f}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Image fetching (tool: view_images)
    # ------------------------------------------------------------------

    @staticmethod
    def _encode(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode("utf-8")

    def _view_images(self, paths: list[str]) -> list[dict]:
        """
        Return a multimodal content list suitable for a ToolMessage.
        Format: alternating text label + image block for each path.
        """
        content: list[dict] = []
        seen: set[str] = set()
        for raw_path in paths[:_MAX_IMAGES_PER_CALL]:
            p = Path(raw_path.strip())
            if str(p) in seen:
                continue
            seen.add(str(p))
            if not p.exists():
                content.append({"type": "text", "text": f"[NOT FOUND: {p}]"})
                continue
            mime = _MIME.get(p.suffix.lower(), "image/jpeg")
            content.append({"type": "text", "text": f"[{p.name}  |  {p}]"})
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{self._encode(p)}"},
            })
        return content

    # ------------------------------------------------------------------
    # Tool dispatcher
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_call: dict, section_dir: Path) -> list[dict] | str:
        name = tool_call.get("name", "")
        args = tool_call.get("args", {})

        if name == "list_images":
            return self._list_images(section_dir)

        if name == "view_images":
            paths = args.get("paths", [])
            self._log.info("Agent viewing images", section=section_dir.name, count=len(paths))
            return self._view_images(paths)

        return f"Unknown tool: {name}"

    # ------------------------------------------------------------------
    # JSON extraction from final model response
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(raw: str | list) -> dict:
        if isinstance(raw, list):
            raw = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in raw)
        raw = raw.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        start = raw.find("{")
        if start == -1:
            raise ValueError("No JSON object found in section analyser response.")
        depth, end = 0, -1
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            raise ValueError("Unterminated JSON in section analyser response.")
        return json.loads(raw[start: end + 1])

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    @staticmethod
    def _system_prompt(output_language: str) -> str:
        return (
            "You are DepthAI, an advanced medical imaging AI specialised in musculoskeletal MRI analysis.\n"
            "You are analysing a SINGLE anatomical section of a knee MRI.\n\n"
            "WORKFLOW — follow exactly:\n"
            "  1. Call list_images to see what is available in this section.\n"
            "  2. Call view_images with the paths you want to examine — choose deliberately.\n"
            "     You may call view_images multiple times (different series, different slices).\n"
            "  3. When you have enough information, stop calling tools and output your final JSON.\n\n"
            "IMAGE SELECTION GUIDANCE:\n"
            "  - For ligament assessment: prioritise oblique/dedicated ACL sequences and T2 sagittal.\n"
            "  - For menisci: prioritise sagittal PD and coronal sequences — check posterior horns.\n"
            "  - For cartilage: fat-suppressed sequences (PD FS, water-selective) show defects best.\n"
            "  - Always examine both ends of a series (first, middle, last slices) before sampling more.\n"
            "  - If you see something suspicious, request adjacent slices to confirm.\n\n"
            f"OUTPUT LANGUAGE: All text fields MUST be written in {output_language}.\n\n"
            "FINAL OUTPUT: When done, respond with a single valid JSON object matching the provided schema. "
            "No markdown, no text outside the JSON. "
            "For images_used: include the absolute paths of the 2-3 most diagnostically relevant images you examined."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse(
        self,
        section_dir: Path,
        section_prompt: str,
        patient_context: str,
        output_language: str = "English",
        laterality: str | None = None,
    ) -> SectionResult:
        section_folder = section_dir.name

        self._log.info("Section agent started", section=section_folder)

        schema = json.dumps(SectionResult.model_json_schema(), indent=2)

        system_content = self._system_prompt(output_language)
        if laterality == "Left":
            system_content += (
                "\n\nLATERALITY (from DICOM): LEFT KNEE. "
                "On coronal images: MEDIAL is viewer's left, LATERAL is viewer's right."
            )
        elif laterality == "Right":
            system_content += (
                "\n\nLATERALITY (from DICOM): RIGHT KNEE. "
                "On coronal images: MEDIAL is viewer's right, LATERAL is viewer's left."
            )

        user_text = (
            f"{section_prompt}\n\n"
            f"## PATIENT CONTEXT\n{patient_context}\n\n"
            f"## OUTPUT SCHEMA\nReturn a JSON object matching this schema:\n{schema}\n\n"
            "Start by calling list_images to see what is available."
        )

        tools = [_LIST_IMAGES_TOOL, _VIEW_IMAGES_TOOL]
        model_with_tools = self._model.bind_tools(tools)

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_text),
        ]

        # Agentic tool-calling loop
        for round_num in range(_MAX_TOOL_ROUNDS):
            response = model_with_tools.invoke(messages)
            messages.append(response)

            tool_calls = getattr(response, "tool_calls", [])
            if not tool_calls:
                # No more tool calls — model has produced its final answer
                self._log.info(
                    "Section agent finished",
                    section=section_folder,
                    rounds=round_num + 1,
                )
                break

            # Execute each tool and feed results back
            for tc in tool_calls:
                result = self._execute_tool(tc, section_dir)
                # ToolMessage content can be a string or a multimodal list
                messages.append(ToolMessage(
                    content=result,
                    tool_call_id=tc["id"],
                ))
        else:
            # Hit max rounds — force the model to output JSON now
            self._log.warning(
                "Section agent hit max rounds — forcing output",
                section=section_folder,
            )
            messages.append(HumanMessage(
                content="You have reached the maximum number of tool calls. "
                        "Output your final JSON now based on what you have seen."
            ))
            response = self._model.invoke(messages)
            messages.append(response)

        # Parse final JSON from last non-tool-call response
        raw = self._extract_json(response.content)

        raw["section_folder"] = section_folder
        if not raw.get("section_title"):
            raw["section_title"] = section_folder.split("_", 1)[-1].replace("_", " ").title()

        result = SectionResult.model_validate(raw)
        self._log.info(
            "Section analysis complete",
            section=section_folder,
            status=result.status,
        )
        return result
