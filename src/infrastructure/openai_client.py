import json
import os
from pathlib import Path

from openai import OpenAI

from src.application.entities.analysis_result import AnalysisResult


class OpenAIClient:
    def __init__(self, client: OpenAI) -> None:
        self._client = client
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o")

    def call_vision(
        self,
        images_by_series: dict[str, list[str]],
        patient_context: str,
        prompt_path: Path | None = None,
    ) -> AnalysisResult:
        prompt = self._load_prompt(prompt_path)
        content = self._build_content(prompt, patient_context, images_by_series)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
            max_tokens=4096,
            temperature=0,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        return AnalysisResult.model_validate(json.loads(raw))

    def _build_content(
        self,
        prompt: str,
        patient_context: str,
        images_by_series: dict[str, list[str]],
    ) -> list[dict]:
        filled = prompt.replace("{patient_context}", patient_context)
        content: list[dict] = [{"type": "text", "text": filled}]

        for label, b64_list in images_by_series.items():
            content.append({"type": "text", "text": f"\n--- Series: {label} ---"})
            for b64 in b64_list:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
                })

        return content

    def _load_prompt(self, prompt_path: Path | None) -> str:
        if prompt_path and prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
