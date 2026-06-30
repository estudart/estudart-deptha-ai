"""
LLM client — patient classification only.

Vision analysis is handled by MriAnalysisAgent (application layer).

Switch models with env vars only, zero code changes:
  LLM_PROVIDER = openai | google | anthropic
  LLM_MODEL    = gpt-4o | gemini-2.5-pro | claude-opus-4-5 | ...
"""

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage


class LLMClient:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

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
