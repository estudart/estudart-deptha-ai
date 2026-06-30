"""
MRI Analysis Agent — tool-calling agent that explores the organised exam folder on demand.

The ExamOrganiser pre-step structures the exam into section folders before this agent
runs. The agent calls list_sections to discover what is available, then get_images to
fetch specific slices per section — choosing which indices to examine.

Tool calling protocol (cross-provider compatible):
  - ToolMessage content is always plain text (OpenAI / Gemini constraint).
  - After each round-trip that produced get_images calls, a HumanMessage carrying
    the actual image blocks is injected before the next model invocation.
"""

import json
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.application.agents.tools import TOOL_SCHEMAS, make_dispatch
from src.infrastructure.logger import Logger

_MAX_ITERATIONS = 40


class MriAnalysisAgent:
    """
    Stateless — each run() call is fully independent.
    All mutable state lives inside run() via closures passed to build_tools().
    """

    def __init__(
        self,
        model: BaseChatModel,
        output_schema: str,
        logger: Logger,
    ) -> None:
        self._model_with_tools = model.bind_tools(TOOL_SCHEMAS)  # bound once, reused every run
        self._output_schema    = output_schema
        self._log              = logger

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _system_prompt(self, output_language: str, laterality: str | None) -> str:
        lines = [
            "You are DepthAI, an advanced medical imaging AI specialised in musculoskeletal MRI analysis.",
            "You have two tools: list_sections (discover available anatomical sections) and get_images (fetch images to examine).",
            "WORKFLOW:",
            "  1. Call list_sections to see all available anatomical sections.",
            "  2. For each section, call get_images with the section name and the slice indices you want to examine.",
            "  3. After examining all sections, return the final JSON — no more tool calls, just the JSON.",
            f"MANDATORY: All text fields in your final JSON MUST be written in {output_language}.",
            "Respond with a single valid JSON object — no markdown, no text outside the JSON.",
        ]
        if laterality == "Left":
            lines.append(
                "CONFIRMED FROM DICOM METADATA — THIS IS A LEFT KNEE. "
                "On coronal images: MEDIAL compartment is on the viewer's LEFT, "
                "LATERAL compartment is on the viewer's RIGHT. This is authoritative."
            )
        elif laterality == "Right":
            lines.append(
                "CONFIRMED FROM DICOM METADATA — THIS IS A RIGHT KNEE. "
                "On coronal images: MEDIAL compartment is on the viewer's RIGHT, "
                "LATERAL compartment is on the viewer's LEFT. This is authoritative."
            )
        return "\n".join(lines)

    def _user_prompt(self, patient_context: str, prompt_path: Path) -> str:
        raw = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        schema_block = (
            "OUTPUT SCHEMA (JSON Schema — for reference only):\n"
            "Respond with a single JSON *instance* that validates against this schema. "
            "Do NOT return the schema itself.\n\n"
            + self._output_schema
        )
        return (
            raw
            .replace("{patient_context}", patient_context)
            .replace("{output_schema}", schema_block)
        )

    # ------------------------------------------------------------------
    # JSON extraction (brace counter — robust against markdown fences)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        start = raw.find("{")
        if start == -1:
            raise ValueError("No JSON object found in agent response.")
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
            raise ValueError("Unterminated JSON object in agent response.")
        return json.loads(raw[start : end + 1])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        organised_dir: Path,
        patient_context: str,
        prompt_path: Path,
        output_language: str = "English",
        laterality: str | None = None,
    ) -> tuple[dict, dict[str, dict[str, str]]]:
        """
        Run the agent loop over the organised exam directory.

        Returns:
            analysis_dict  — raw JSON dict (validated into AnalysisResult by the service)
            images_used    — {section_folder: {file_path: file_path}} of every image
                             the agent actually fetched. Paths are absolute (local now,
                             bucket URL in the future). Report builder reads from these paths.
        """
        images_used: dict[str, dict[str, str]] = {}
        dispatch = make_dispatch(organised_dir, images_used, self._log)

        section_count = sum(1 for p in organised_dir.iterdir() if p.is_dir())
        self._log.info("Agent run started", organised_sections=section_count)

        messages = [
            SystemMessage(content=self._system_prompt(output_language, laterality)),
            HumanMessage(content=self._user_prompt(patient_context, prompt_path)),
        ]

        for iteration in range(_MAX_ITERATIONS):
            response: AIMessage = self._model_with_tools.invoke(messages)
            messages.append(response)

            # No tool calls → agent is done, extract final JSON
            if not response.tool_calls:
                self._log.info("Agent finished", iterations=iteration + 1)
                raw = response.content
                if not raw or not raw.strip():
                    raise ValueError("Agent returned an empty final response.")
                return self._extract_json(raw), images_used

            self._log.info(
                "Agent iteration",
                iteration=iteration + 1,
                tool_calls=[tc["name"] for tc in response.tool_calls],
            )

            # Process all tool calls — ToolMessages first (text only, cross-provider safe)
            image_blocks: list[dict] = []

            for tc in response.tool_calls:
                fn = dispatch.get(tc["name"])
                if fn is None:
                    result_text = json.dumps({"error": f"Unknown tool '{tc['name']}'"})
                else:
                    result_text = fn(tc["args"])

                messages.append(ToolMessage(content=result_text, tool_call_id=tc["id"]))

                # Collect images encoded during this tool call.
                # tools.py stores b64 transiently under "{path}:b64" sidecar keys.
                if tc["name"] == "get_images":
                    section = tc["args"].get("section", "")
                    bucket  = images_used.get(section, {})
                    for key in [k for k in bucket if k.endswith(":b64")]:
                        image_blocks.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{bucket.pop(key)}"},
                        })

            # Inject images as a separate HumanMessage (cross-provider compatible)
            if image_blocks:
                messages.append(HumanMessage(content=image_blocks))

        raise RuntimeError(
            f"Agent did not produce a final answer within {_MAX_ITERATIONS} iterations."
        )
