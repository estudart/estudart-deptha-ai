"""
LLM client — provider-agnostic via LangChain.

Switch models with env vars only, zero code changes:
  LLM_PROVIDER = openai | google | anthropic
  LLM_MODEL    = gpt-4o | gemini-2.5-pro | claude-opus-4-5 | ...

Pipeline:
  Stage 1 — classify_patient()       : cheap text call, selects prompt
  Stage 2 — call_section_vision()    : one vision call per section, only that section's images
  Stage 3 — call_synthesis()         : text-only call, assembles summary / clinical answer / flags
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
    # Stage 1 — patient classification
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
            lower = response.content.lower()
            if "post_op" in lower or "post-op" in lower:
                return "post_op"
            if "degenerative" in lower:
                return "degenerative"
            return "native_trauma"

    # ------------------------------------------------------------------
    # Stage 2 — per-section vision analysis
    # ------------------------------------------------------------------

    def call_section_vision(
        self,
        section_name: str,
        section_images: dict[str, dict[str, str]],  # series → {filename: b64}
        patient_context: str,
        clinical_guidelines: str,                    # extracted from full prompt
        laterality: str | None,
        output_language: str = "English",
    ) -> dict:
        """
        Analyse one anatomical section using only that section's images.
        Returns a Section-compatible dict.
        """
        all_filenames = [fn for slices in section_images.values() for fn in slices]

        section_schema = {
            "title": section_name,
            "series_label": "<exact series label from the image list>",
            "best_slice_filenames": ["<filename1>", "<filename2>"],
            "status": "<normal | attention | significant>",
            "subsections": [
                {"title": "<sub-structure name>", "findings": ["<finding 1>", "<finding 2>"]}
            ],
            "reasoning": "<2-4 sentence radiological reasoning>",
            "notes": ["<interpretive note for radiologist>"],
        }

        lat_note = self._laterality_note(laterality)

        system_msg = (
            f"You are DepthAI, an advanced medical imaging AI specialized in musculoskeletal MRI. "
            f"You are analysing ONE section: '{section_name}'. "
            f"IMPORTANT: All text MUST be in {output_language}. "
            f"Respond with a single valid JSON object — no markdown, no text outside JSON."
        )

        task = (
            f"SECTION TO ANALYSE: {section_name}\n\n"
            f"PATIENT CONTEXT:\n{patient_context}\n\n"
            f"{lat_note}\n\n"
            f"CLINICAL GUIDELINES (apply these criteria to your analysis):\n{clinical_guidelines}\n\n"
            f"AVAILABLE IMAGES — these are ALL the images you have for this section:\n"
            f"Series: {list(section_images.keys())}\n"
            f"Filenames: {json.dumps(all_filenames)}\n\n"
            f"TASK: Analyse the images below and return a JSON object matching this structure:\n"
            f"{json.dumps(section_schema, indent=2)}\n\n"
            f"RULES:\n"
            f"- best_slice_filenames: pick 2-3 filenames from {json.dumps(all_filenames)} "
            f"that best show the key finding. ONLY use filenames from this list.\n"
            f"- series_label: use the exact series label as shown above.\n"
            f"- All text fields in {output_language}.\n"
            f"LANGUAGE REQUIREMENT — MANDATORY: Every text field MUST be in {output_language}."
        )

        content: list[dict] = [{"type": "text", "text": task}]
        for label, slices in section_images.items():
            for filename, b64 in slices.items():
                content.append({"type": "text", "text": f"[{label} | {filename}]"})
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "auto"},
                })

        response = self._model.invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=content),
        ])

        raw = response.content
        if not raw or not raw.strip():
            raise ValueError(f"Empty response for section '{section_name}'.")

        result = self._extract_json(raw)
        result["title"] = section_name  # ensure title matches exactly

        # Ensure series_label is one we actually sent
        valid_labels = list(section_images.keys())
        if result.get("series_label") not in valid_labels:
            result["series_label"] = valid_labels[0]

        # Enforce valid filenames — must belong to the resolved series_label
        primary_series = result["series_label"]
        primary_filenames = list(section_images[primary_series].keys())
        valid = set(all_filenames)

        filtered = [f for f in result.get("best_slice_filenames", []) if f in valid]
        if not filtered:
            # Fallback: 3 central filenames from the primary series
            mid = len(primary_filenames) // 2
            filtered = primary_filenames[max(0, mid - 1): mid + 2]
        result["best_slice_filenames"] = filtered[:3]

        return result

    # ------------------------------------------------------------------
    # Stage 3 — synthesis (text only, no images)
    # ------------------------------------------------------------------

    def call_synthesis(
        self,
        sections: list[dict],
        patient_context: str,
        clinical_guidelines: str,
        output_language: str = "English",
    ) -> dict:
        """
        Text-only call that receives all section results and produces:
        summary, clinical_answer, flags.
        """
        synthesis_schema = {
            "summary": [
                {"label": "<structure name>", "status": "<normal|attention|significant>", "text": "<one sentence>"}
            ],
            "clinical_answer": {
                "question": "<restate primary clinical question>",
                "answer": "<2-3 sentence direct answer>",
                "confidence": "<High|Moderate|Low>",
                "limiting_factors": "<limitations or 'None'>",
            },
            "flags": ["<finding requiring priority radiologist review>"],
        }

        system_msg = (
            f"You are DepthAI, a medical imaging AI. "
            f"You have received section-by-section MRI analysis results. "
            f"Synthesize them into a summary, clinical answer, and flags. "
            f"All text MUST be in {output_language}. "
            f"Respond with a single valid JSON object — no markdown."
        )

        task = (
            f"PATIENT CONTEXT:\n{patient_context}\n\n"
            f"CLINICAL GUIDELINES:\n{clinical_guidelines}\n\n"
            f"SECTION RESULTS (from individual section analyses):\n"
            f"{json.dumps(sections, indent=2)}\n\n"
            f"TASK: Based on ALL section results above, return a JSON object:\n"
            f"{json.dumps(synthesis_schema, indent=2)}\n\n"
            f"RULES:\n"
            f"- summary: one item per key structure, derived from section findings\n"
            f"- clinical_answer: directly answer the primary clinical question\n"
            f"- flags: list ONLY findings that require urgent radiologist attention; "
            f"if none, use ['No priority flags.']\n"
            f"- All text in {output_language}."
        )

        response = self._model.invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=task),
        ])

        raw = response.content
        if not raw or not raw.strip():
            raise ValueError("Empty response for synthesis call.")
        return self._extract_json(raw)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _laterality_note(self, laterality: str | None) -> str:
        if laterality == "Left":
            return (
                "CONFIRMED FROM DICOM METADATA — THIS IS A LEFT KNEE. "
                "On coronal images: MEDIAL compartment is on the viewer's LEFT, "
                "LATERAL compartment (fibular head, LCL) is on the viewer's RIGHT."
            )
        if laterality == "Right":
            return (
                "CONFIRMED FROM DICOM METADATA — THIS IS A RIGHT KNEE. "
                "On coronal images: MEDIAL compartment is on the viewer's RIGHT, "
                "LATERAL compartment (fibular head, LCL) is on the viewer's LEFT."
            )
        return ""

    def _extract_json(self, raw: str) -> dict:
        """Robustly extract a JSON object — handles markdown fences and trailing text."""
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
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
