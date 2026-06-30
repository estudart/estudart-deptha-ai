import json
import os
from pathlib import Path

from openai import OpenAI


class OpenAIClient:
    def __init__(self, client: OpenAI, output_schema: str) -> None:
        self._client = client
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        self._output_schema = output_schema

    def _build_content(
        self,
        prompt: str,
        patient_context: str,
        images_by_series: dict[str, list[str]],
        output_language: str = "English",
        laterality: str | None = None,
    ) -> list[dict]:
        filled = (
            prompt
            .replace("{patient_context}", patient_context)
            .replace("{output_schema}", self._output_schema)
        )
        content: list[dict] = [{"type": "text", "text": filled}]

        if laterality:
            if laterality == "Left":
                orientation_note = (
                    "CONFIRMED FROM DICOM METADATA — THIS IS A LEFT KNEE. "
                    "On coronal images (standard radiological display): "
                    "the MEDIAL compartment (MCL, medial meniscus) is on the viewer's LEFT side. "
                    "The LATERAL compartment (fibular head, LCL) is on the viewer's RIGHT side. "
                    "This is authoritative — do not override it based on visual guessing."
                )
            else:
                orientation_note = (
                    "CONFIRMED FROM DICOM METADATA — THIS IS A RIGHT KNEE. "
                    "On coronal images (standard radiological display): "
                    "the MEDIAL compartment (MCL, medial meniscus) is on the viewer's RIGHT side. "
                    "The LATERAL compartment (fibular head, LCL) is on the viewer's LEFT side. "
                    "This is authoritative — do not override it based on visual guessing."
                )
            content.append({"type": "text", "text": orientation_note})

        # Language instruction placed prominently before images so it is not lost in the payload
        content.append({"type": "text", "text": (
            f"LANGUAGE REQUIREMENT — MANDATORY: Every text field in your JSON response "
            f"(findings, reasoning, notes, summary text, clinical answer, flags) "
            f"MUST be written in {output_language}. "
            f"Do NOT use any other language. This overrides any language present in the images or prompt examples."
        )})

        # Image manifest — sent before any images so the model knows what's available
        manifest = {
            label: list(slices_by_name.keys())
            for label, slices_by_name in images_by_series.items()
        }
        content.append({
            "type": "text",
            "text": (
                "IMAGE MANIFEST — all series and their filenames in this exam:\n"
                + json.dumps(manifest, indent=2)
                + "\n\nEach image below is labeled [series_label | filename]. "
                "Use the exact series_label and filenames from this manifest "
                "when populating series_label and best_slice_filenames in your response."
            ),
        })

        # Images — each labeled with series name and its actual filename
        for label, slices_by_name in images_by_series.items():
            for filename, b64 in slices_by_name.items():
                content.append({"type": "text", "text": f"[{label} | {filename}]"})
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "auto"},
                })

        return content

    def classify_patient(self, patient_context: str) -> str:
        """
        Stage 1 — lightweight text-only call.
        Returns one of: 'native_trauma', 'post_op', 'degenerative'
        """
        system = (
            "You are a clinical triage assistant. Read the patient context and classify it "
            "into exactly one of these profiles:\n\n"
            "- 'post_op': patient has prior knee surgery (ACL reconstruction, meniscal repair, "
            "osteotomy, arthroplasty, or any other knee procedure) — regardless of whether the "
            "current concern is related to the surgery.\n"
            "- 'native_trauma': no prior knee surgery; current presentation is acute or subacute "
            "traumatic injury (fall, sports injury, twisting mechanism, direct impact).\n"
            "- 'degenerative': no prior knee surgery; presentation is chronic, gradual onset, "
            "age-related, or OA-related — no clear acute trauma.\n\n"
            "Respond with a JSON object: {\"profile\": \"<one of the three values>\"}"
        )
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": patient_context},
            ],
            max_tokens=50,
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = json.loads(response.choices[0].message.content or "{}")
        return raw.get("profile", "native_trauma")

    def _load_prompt(self, prompt_path: Path | None) -> str:
        if prompt_path and prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")

    def call_vision(
        self,
        images_by_series: dict[str, list[str]],
        patient_context: str,
        prompt_path: Path | None = None,
        output_language: str = "English",
        laterality: str | None = None,
    ) -> dict:
        prompt = self._load_prompt(prompt_path)
        content = self._build_content(prompt, patient_context, images_by_series, output_language, laterality)

        system_msg = (
            f"You are DepthAI, an advanced medical imaging AI assistant. "
            f"IMPORTANT: All text in your JSON response MUST be written in {output_language}."
        )
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": content},
            ],
            max_tokens=8192,
            temperature=0,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        if not raw:
            reason = response.choices[0].finish_reason
            raise ValueError(
                f"GPT-4o returned an empty response (finish_reason={reason!r}). "
                "The image payload may be too large — try reducing --slices."
            )
        return json.loads(raw)
