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

from src.application.entities.analysis_result import AnalysisResult
from src.application.services.analysis_service import AnalysisService
from src.infrastructure.dicom_reader import DicomReader
from src.infrastructure.image_encoder import ImageEncoder
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.logger import Logger

_logger: Logger | None = None
_llm_client: LLMClient | None = None
_analysis_service: AnalysisService | None = None


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
            model_kwargs={"response_format": {"type": "json_object"}},
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=os.environ["GOOGLE_API_KEY"],
            temperature=0,
            max_output_tokens=8192,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        # Anthropic has no JSON mode — rely on prompt-level instruction
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
        _llm_client = LLMClient(
            model=_make_chat_model(),
            output_schema=json.dumps(AnalysisResult.model_json_schema(), indent=2),
        )
    return _llm_client


def get_analysis_service() -> AnalysisService:
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService(
            dicom_reader=DicomReader(),
            image_encoder=ImageEncoder(),
            llm_client=get_llm_client(),
            logger=get_logger(),
        )
    return _analysis_service
