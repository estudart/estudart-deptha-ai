"""
SectionAnalyser — single-section vision analysis pass.

AGENT — directly invokes a language model (vision).
Lives in src/application/agents/.
Pure utilities (ImageSelector, ExamOrganiser, etc.) live in src/application/services/.

Each anatomical section gets its own dedicated call:
  - Only images from that section's folder (selected by ImageSelector from services/)
  - A medically-rich section-specific prompt
  - Output is a validated SectionResult

No tool-calling loop. One focused call, one structured result.
"""

import base64
import json
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.application.services.image_selector import ImageSelector
from src.application.entities.section_result import SectionResult
from src.infrastructure.logger import Logger

_MIME_TYPES: dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
}


class SectionAnalyser:
    """Stateless — each analyse() call is fully independent."""

    def __init__(self, model: BaseChatModel, logger: Logger) -> None:
        self._model    = model
        self._selector = ImageSelector()
        self._log      = logger

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _system_prompt(self, output_language: str, laterality: str | None) -> str:
        lines = [
            "You are DepthAI, an advanced medical imaging AI specialised in musculoskeletal MRI analysis.",
            "You will receive a set of labelled MRI images for a SINGLE anatomical section.",
            "Each image is preceded by a text label: [Section | Series | Slice N | /path/to/file].",
            "Use the series name in each label to understand which MRI sequence you are viewing.",
            "Analyse ALL images provided before producing your output.",
            f"MANDATORY: All text fields in your JSON output MUST be written in {output_language}.",
            "For images_used: copy 2-3 file paths EXACTLY as they appear after the last '|' in the image labels.",
            "Respond with a single valid JSON object — no markdown, no text outside the JSON.",
        ]
        if laterality == "Left":
            lines.append(
                "CONFIRMED FROM DICOM METADATA — THIS IS A LEFT KNEE. "
                "On coronal images: MEDIAL is on the viewer's LEFT, LATERAL is on the viewer's RIGHT."
            )
        elif laterality == "Right":
            lines.append(
                "CONFIRMED FROM DICOM METADATA — THIS IS A RIGHT KNEE. "
                "On coronal images: MEDIAL is on the viewer's RIGHT, LATERAL is on the viewer's LEFT."
            )
        return "\n".join(lines)

    @staticmethod
    def _encode(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode("utf-8")

    def _image_blocks(self, selected: list[tuple[Path, str]]) -> list[dict]:
        blocks: list[dict] = []
        for path, label in selected:
            mime = _MIME_TYPES.get(path.suffix.lower(), "image/jpeg")
            blocks.append({"type": "text", "text": f"[{label}]"})
            blocks.append({
                "type":      "image_url",
                "image_url": {"url": f"data:{mime};base64,{self._encode(path)}"},
            })
        return blocks

    @staticmethod
    def _extract_json(raw: str | list) -> dict:
        if isinstance(raw, list):
            raw = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in raw)
        raw = raw.strip()
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
        """
        Analyse a single section folder.

        Args:
            section_dir:     Path to the organised section folder (e.g. .../02_menisci/).
            section_prompt:  Full prompt text for this section (medically rich, profile-specific).
            patient_context: Free-text clinical context.
            output_language: Language for all text fields.
            laterality:      "Left" | "Right" | None.

        Returns:
            Validated SectionResult.
        """
        selected = self._selector.select_section(section_dir)
        section_folder = section_dir.name

        self._log.info(
            "Section analysis started",
            section=section_folder,
            images=len(selected),
        )

        schema = json.dumps(SectionResult.model_json_schema(), indent=2)
        user_text = (
            section_prompt
            + f"\n\n## PATIENT CONTEXT\n{patient_context}"
            + f"\n\n## OUTPUT SCHEMA\nReturn a JSON object matching this schema:\n{schema}"
        )

        content = [{"type": "text", "text": user_text}] + self._image_blocks(selected)
        messages = [
            SystemMessage(content=self._system_prompt(output_language, laterality)),
            HumanMessage(content=content),
        ]

        response = self._model.invoke(messages)
        raw      = self._extract_json(response.content)

        # Inject section identity (model doesn't know the folder name)
        raw["section_folder"] = section_folder
        if "section_title" not in raw or not raw["section_title"]:
            raw["section_title"] = section_folder.split("_", 1)[-1].replace("_", " ").title()

        result = SectionResult.model_validate(raw)
        self._log.info(
            "Section analysis complete",
            section=section_folder,
            status=result.status,
        )
        return result
