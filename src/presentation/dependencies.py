"""
Composition root — all singletons created here.

Model switching is done entirely via environment variables:
  LLM_PROVIDER = openai (default) | google | anthropic
  LLM_MODEL    = gpt-4o (default) | gemini-2.5-pro | claude-opus-4-5 | etc.

No code changes needed to swap models.
"""

import json
import os

from langchain_core.language_models import BaseChatModel

from src.application.agents.mri_analysis_agent import MriAnalysisAgent
from src.application.entities.analysis_result import AnalysisResult
from src.application.services.analysis_service import AnalysisService
from src.application.services.exam_organiser import ExamOrganiser
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.logger import Logger

_logger:             Logger | None           = None
_llm_client:         LLMClient | None        = None
_exam_organiser:     ExamOrganiser | None    = None
_mri_analysis_agent: MriAnalysisAgent | None = None
_analysis_service:   AnalysisService | None  = None


def get_logger() -> Logger:
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger


def _make_chat_model() -> BaseChatModel:
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    model    = os.environ.get("LLM_MODEL",    "gpt-4o")

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=os.environ["OPENAI_API_KEY"],
            max_tokens=8192,
            temperature=0,
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=os.environ["GOOGLE_API_KEY"],
            temperature=0,
            max_output_tokens=32768,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            api_key=os.environ["ANTHROPIC_API_KEY"],
            max_tokens=8192,
            temperature=0,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER='{provider}'. "
        "Supported: openai | google | anthropic"
    )


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        provider = os.environ.get("LLM_PROVIDER", "openai")
        model    = os.environ.get("LLM_MODEL",    "gpt-4o")
        get_logger().info("LLM initialised", provider=provider, model=model)
        _llm_client = LLMClient(model=_make_chat_model())
    return _llm_client


def get_exam_organiser() -> ExamOrganiser:
    global _exam_organiser
    if _exam_organiser is None:
        _exam_organiser = ExamOrganiser(logger=get_logger())
    return _exam_organiser


def get_mri_analysis_agent() -> MriAnalysisAgent:
    global _mri_analysis_agent
    if _mri_analysis_agent is None:
        _mri_analysis_agent = MriAnalysisAgent(
            model=_make_chat_model(),
            output_schema=json.dumps(AnalysisResult.model_json_schema(), indent=2),
            logger=get_logger(),
        )
    return _mri_analysis_agent


def get_analysis_service() -> AnalysisService:
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService(
            llm_client=get_llm_client(),
            exam_organiser=get_exam_organiser(),
            agent=get_mri_analysis_agent(),
            logger=get_logger(),
        )
    return _analysis_service
