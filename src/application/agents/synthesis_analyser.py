"""
SynthesisAnalyser — text-only final synthesis pass.

AGENT — directly invokes a language model (text only, no images).
Lives in src/application/agents/.

Receives all SectionResult texts, produces a SynthesisResult:
  - Summary table across all structures
  - Direct answer to the primary clinical question
  - Priority flags for radiologist review

No images. No tool-calling. One focused call, one structured result.
"""

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.application.entities.section_result import SectionResult
from src.application.entities.synthesis_result import SynthesisResult
from src.infrastructure.logger import Logger

_SYSTEM_PROMPT = """\
You are DepthAI, an advanced medical imaging AI specialised in musculoskeletal MRI analysis.
You will receive structured findings from multiple anatomical section analyses of a single knee MRI exam.
Each section was analysed independently; your task is to integrate them into a coherent clinical synthesis.

Rules:
- Cross-reference findings across sections (e.g. bone bruise pattern suggests ACL tear mechanism).
- Do NOT repeat raw findings — synthesise, correlate, and conclude.
- The summary must cover every key structure assessed across all sections.
- Flags must identify only genuinely urgent or unexpected findings; do not flag normal variation.
- Be clinically direct. This is a pre-read for a radiologist, not a patient letter.
- Respond with a single valid JSON object — no markdown, no text outside the JSON.
"""


class SynthesisAnalyser:
    """Stateless — each synthesise() call is fully independent."""

    def __init__(self, model: BaseChatModel, logger: Logger) -> None:
        self._model = model
        self._log   = logger

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_sections(sections: list[SectionResult]) -> str:
        parts: list[str] = []
        for sec in sections:
            lines = [f"## {sec.section_title.upper()}  [{sec.status.upper()}]"]
            lines.append(f"Reasoning: {sec.reasoning}")
            for sub in sec.subsections:
                lines.append(f"### {sub.title}")
                for f in sub.findings:
                    lines.append(f"  - {f}")
            if sec.notes:
                lines.append("Notes:")
                for n in sec.notes:
                    lines.append(f"  > {n}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

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
            raise ValueError("No JSON object found in synthesis analyser response.")
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
            raise ValueError("Unterminated JSON in synthesis analyser response.")
        return json.loads(raw[start: end + 1])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def synthesise(
        self,
        sections: list[SectionResult],
        patient_context: str,
        clinical_question: str,
        output_language: str = "English",
    ) -> SynthesisResult:
        """
        Produce a final synthesis from all section results.

        Args:
            sections:          Validated SectionResult list (all sections).
            patient_context:   Free-text clinical context.
            clinical_question: The primary clinical question to answer.
            output_language:   Language for all text fields.

        Returns:
            Validated SynthesisResult.
        """
        self._log.info("Synthesis started", sections=len(sections))

        schema = json.dumps(SynthesisResult.model_json_schema(), indent=2)
        section_text = self._format_sections(sections)

        user_content = (
            f"## PATIENT CONTEXT\n{patient_context}\n\n"
            f"## PRIMARY CLINICAL QUESTION\n{clinical_question}\n\n"
            f"## SECTION FINDINGS\n{section_text}\n\n"
            f"## OUTPUT LANGUAGE\nAll text fields MUST be written in {output_language}.\n\n"
            f"## OUTPUT SCHEMA\nReturn a JSON object matching this schema:\n{schema}"
        )

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]

        response = self._model.invoke(messages)
        raw      = self._extract_json(response.content)

        result = SynthesisResult.model_validate(raw)
        self._log.info("Synthesis complete", flags=len(result.flags))
        return result
