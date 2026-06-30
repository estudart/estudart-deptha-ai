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

        content.append({"type": "text", "text": f"IMPORTANT: Write all text fields in the JSON response in {output_language}."})

        # Image manifest — sent before any images so the model knows the full index
        manifest = {
            label: {"slice_count": len(b64_list), "indices": list(range(len(b64_list)))}
            for label, b64_list in images_by_series.items()
        }
        content.append({
            "type": "text",
            "text": (
                "IMAGE MANIFEST — complete index of all series and slices in this exam:\n"
                + json.dumps(manifest, indent=2)
                + "\n\nUse the exact series labels and slice indices from this manifest "
                "when populating series_label and best_slice_indices in your response."
            ),
        })

        # Images — each fully labeled with series name and slice index inline
        for label, b64_list in images_by_series.items():
            for idx, b64 in enumerate(b64_list):
                content.append({"type": "text", "text": f"[{label} | Slice {idx}]"})
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

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
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
