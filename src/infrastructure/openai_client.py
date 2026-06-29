import os
from pathlib import Path

from openai import OpenAI


class OpenAIClient:
    def __init__(self, client: OpenAI) -> None:
        self._client = client
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o")

    def call_vision(
        self,
        images_by_series: dict[str, list[str]],
        patient_context: str,
        prompt_path: Path | None = None,
    ) -> str:
        prompt = self._load_prompt(prompt_path)
        content = self._build_content(prompt, patient_context, images_by_series)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
            max_tokens=4096,
            temperature=1
        )
        return response.choices[0].message.content

    def _build_content(
        self,
        prompt: str,
        patient_context: str,
        images_by_series: dict[str, list[str]],
    ) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": prompt.format(patient_context=patient_context)}]

        for label, b64_list in images_by_series.items():
            content.append({"type": "text", "text": f"\n--- Série: {label} ---"})
            for b64 in b64_list:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
                })

        return content

    def _load_prompt(self, prompt_path: Path | None) -> str:
        if prompt_path and prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return self._default_prompt()

    def _default_prompt(self) -> str:
        return """
            Você é um radiologista assistente especializado em RM musculoesquelética.

            Contexto clínico:
            {patient_context}

            Analise as séries abaixo e produza um laudo estruturado com:
            1. Estruturas visíveis por série
            2. Achados relevantes (edema, rotura, derrame, alterações de sinal)
            3. Correlação clínica com o contexto
            4. Impressão diagnóstica
            5. Recomendações

            Use terminologia radiológica em português. Indique limitações de qualidade quando presentes.
        """
