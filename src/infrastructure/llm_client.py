"""
LLM client — provider-agnostic via LangChain.

Switch models with env vars only, zero code changes:
  LLM_PROVIDER = openai | google | anthropic
  LLM_MODEL    = gpt-4o | gemini-2.5-pro | claude-opus-4-5 | ...
"""

import json
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage


class LLMClient:
    def __init__(self, model: BaseChatModel, output_schema: str) -> None:
        self._model = model
        self._output_schema = output_schema

    # ------------------------------------------------------------------
    # Stage 1 — cheap text-only classification
    # ------------------------------------------------------------------

    def classify_patient(self, patient_context: str) -> str:
        """Returns one of: 'post_op' | 'native_trauma' | 'degenerative'"""
        system = (
            "You are a clinical triage assistant. Read the patient context and classify it "
            "into exactly one of these profiles:\n\n"
            "- 'post_op': patient has prior knee surgery (ACL reconstruction, meniscal repair, "
            "osteotomy, arthroplasty, or any other knee procedure).\n"
            "- 'native_trauma': no prior surgery; acute/subacute traumatic injury.\n"
            "- 'degenerative': no prior surgery; chronic, gradual onset, age-related.\n\n"
            'Respond with a JSON object: {"profile": "<one of the three values>"}'
        )
        response = self._model.invoke([
            SystemMessage(content=system),
            HumanMessage(content=patient_context),
        ])
        try:
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw).get("profile", "native_trauma")
        except Exception:
            # Last resort: keyword scan
            lower = response.content.lower()
            if "post_op" in lower or "post-op" in lower:
                return "post_op"
            if "degenerative" in lower:
                return "degenerative"
            return "native_trauma"

    # ------------------------------------------------------------------
    # Stage 2 — full vision analysis
    # ------------------------------------------------------------------

    def call_vision(
        self,
        images_by_series: dict[str, dict[str, str]],   # series → {filename: b64}
        patient_context: str,
        prompt_path: Path | None = None,
        output_language: str = "English",
        laterality: str | None = None,
        section_routing: dict[str, list[str]] | None = None,
    ) -> dict:
        prompt = self._load_prompt(prompt_path)
        content = self._build_content(
            prompt, patient_context, images_by_series,
            output_language, laterality, section_routing,
        )
        system_msg = (
            f"You are DepthAI, an advanced medical imaging AI assistant specialized in "
            f"musculoskeletal MRI analysis. "
            f"IMPORTANT: All text in your JSON response MUST be written in {output_language}. "
            f"Respond with a single valid JSON object — no markdown, no text outside JSON."
        )
        response = self._model.invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=content),
        ])
        raw = response.content
        if not raw or not raw.strip():
            raise ValueError("LLM returned an empty response. Payload may be too large.")
        return self._extract_json(raw)

    # ------------------------------------------------------------------
    # Content builder
    # ------------------------------------------------------------------

    def _build_content(
        self,
        prompt: str,
        patient_context: str,
        images_by_series: dict[str, dict[str, str]],
        output_language: str = "English",
        laterality: str | None = None,
        section_routing: dict[str, list[str]] | None = None,
    ) -> list[dict]:
        filled = (
            prompt
            .replace("{patient_context}", patient_context)
            .replace("{output_schema}", self._output_schema)
        )
        content: list[dict] = [{"type": "text", "text": filled}]

        # Laterality — injected as authoritative fact
        if laterality:
            if laterality == "Left":
                note = (
                    "CONFIRMED FROM DICOM METADATA — THIS IS A LEFT KNEE. "
                    "On coronal images (standard radiological display): "
                    "MEDIAL compartment (MCL, medial meniscus) is on the viewer's LEFT. "
                    "LATERAL compartment (fibular head, LCL) is on the viewer's RIGHT. "
                    "This is authoritative — do not override based on visual guessing."
                )
            else:
                note = (
                    "CONFIRMED FROM DICOM METADATA — THIS IS A RIGHT KNEE. "
                    "On coronal images (standard radiological display): "
                    "MEDIAL compartment (MCL, medial meniscus) is on the viewer's RIGHT. "
                    "LATERAL compartment (fibular head, LCL) is on the viewer's LEFT. "
                    "This is authoritative — do not override based on visual guessing."
                )
            content.append({"type": "text", "text": note})

        # Language enforcement
        content.append({"type": "text", "text": (
            f"LANGUAGE REQUIREMENT — MANDATORY: Every text field in your JSON response "
            f"MUST be written in {output_language}. No other language."
        )})

        # IMAGE MANIFEST — includes section routing so model knows which series to use per section
        manifest: dict = {
            "series_filenames": {
                label: list(slices.keys())
                for label, slices in images_by_series.items()
            }
        }
        if section_routing:
            manifest["section_routing"] = section_routing

        routing_instruction = ""
        if section_routing:
            routing_instruction = (
                "\n\nSECTION IMAGE ROUTING — MANDATORY:\n"
                "The manifest above contains a 'section_routing' map. "
                "For each section in your JSON response:\n"
                "  - series_label MUST be one of the series listed for that section\n"
                "  - best_slice_filenames MUST be filenames from that section's series only\n"
                "Do NOT use a series from another section's routing. "
                "If a section has no routing entry, use your judgment."
            )

        content.append({
            "type": "text",
            "text": (
                "IMAGE MANIFEST:\n"
                + json.dumps(manifest, indent=2)
                + "\n\nEach image below is labeled [series_label | filename]."
                + routing_instruction
            ),
        })

        # Images — each sent EXACTLY ONCE, labeled with a section header on first appearance.
        # The section_routing manifest already tells the model which series → section;
        # we don't need to physically repeat images across sections.
        if section_routing:
            # Build reverse map: series_label → first section that claims it
            series_to_section: dict[str, str] = {}
            for section_name, series_labels in section_routing.items():
                for lbl in series_labels:
                    if lbl not in series_to_section:
                        series_to_section[lbl] = section_name

            # Group series by their first-claiming section, preserving section order
            from collections import defaultdict
            section_series: dict[str, list[str]] = defaultdict(list)
            for lbl in images_by_series:
                sec = series_to_section.get(lbl, "Other")
                section_series[sec].append(lbl)

            for section_name, series_labels in section_routing.items():
                group = section_series.get(section_name, [])
                if not group:
                    continue
                content.append({"type": "text", "text": (
                    f"\n{'='*60}\n"
                    f"IMAGES FOR SECTION: {section_name}\n"
                    f"Use ONLY these series for '{section_name}': {group}\n"
                    f"{'='*60}"
                )})
                for label in group:
                    for filename, b64 in images_by_series[label].items():
                        content.append({"type": "text", "text": f"[{label} | {filename}]"})
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "auto"},
                        })
        else:
            # Fallback — flat list (original behaviour)
            for label, slices_by_name in images_by_series.items():
                for filename, b64 in slices_by_name.items():
                    content.append({"type": "text", "text": f"[{label} | {filename}]"})
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "auto"},
                    })

        return content

    def _extract_json(self, raw: str) -> dict:
        """Robustly extract a JSON object from LLM output that may contain markdown fences or trailing text."""
        raw = raw.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        # Extract the outermost JSON object — handles trailing text after closing brace
        start = raw.find("{")
        if start == -1:
            raise ValueError("No JSON object found in LLM response.")
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
            raise ValueError("Unterminated JSON object in LLM response.")
        return json.loads(raw[start:end + 1])

    def _load_prompt(self, prompt_path: Path | None) -> str:
        if prompt_path and prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
