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
    ) -> list[dict]:
        filled = (
            prompt
            .replace("{patient_context}", patient_context)
            .replace("{output_schema}", self._output_schema)
        )
        content: list[dict] = [
            {"type": "text", "text": filled},
            {"type": "text", "text": f"IMPORTANT: Write all text fields in the JSON response in {output_language}."},
        ]

        for label, b64_list in images_by_series.items():
            content.append({"type": "text", "text": f"\n--- Series: {label} ---"})
            for idx, b64 in enumerate(b64_list):
                content.append({"type": "text", "text": f"[Slice {idx}]"})
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "auto"},
                })

        return content

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
    ) -> dict:
        prompt = self._load_prompt(prompt_path)
        content = self._build_content(prompt, patient_context, images_by_series, output_language)

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
