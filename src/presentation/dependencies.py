"""
Composition root — all singletons created here.

Model switching is done entirely via environment variables:
  LLM_PROVIDER = anthropic (default) | openai | google
  LLM_MODEL    = claude-opus-4-5 (default) | gpt-4o | gemini-2.5-pro | etc.

No code changes needed to swap models.
"""

import os

from langchain_core.language_models import BaseChatModel

from src.application.agents.section_analyser import SectionAnalyser
from src.application.agents.synthesis_analyser import SynthesisAnalyser
from src.application.services.analysis_service import AnalysisService
from src.infrastructure.logger import Logger

_logger:             Logger | None            = None
_section_analyser:   SectionAnalyser | None   = None
_synthesis_analyser: SynthesisAnalyser | None = None
_analysis_service:   AnalysisService | None   = None


def get_logger() -> Logger:
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger


def _make_chat_model() -> BaseChatModel:
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    model    = os.environ.get("LLM_MODEL",    "claude-opus-4-5")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            api_key=os.environ["ANTHROPIC_API_KEY"],
            max_tokens=8192,
            temperature=0,
        )

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

    raise ValueError(
        f"Unknown LLM_PROVIDER='{provider}'. "
        "Supported: anthropic | openai | google"
    )


def get_section_analyser() -> SectionAnalyser:
    global _section_analyser
    if _section_analyser is None:
        _section_analyser = SectionAnalyser(
            model=_make_chat_model(),
            logger=get_logger(),
        )
    return _section_analyser


def get_synthesis_analyser() -> SynthesisAnalyser:
    global _synthesis_analyser
    if _synthesis_analyser is None:
        _synthesis_analyser = SynthesisAnalyser(
            model=_make_chat_model(),
            logger=get_logger(),
        )
    return _synthesis_analyser


def get_analysis_service() -> AnalysisService:
    global _analysis_service
    if _analysis_service is None:
        provider = os.environ.get("LLM_PROVIDER", "anthropic")
        model    = os.environ.get("LLM_MODEL",    "claude-opus-4-5")
        get_logger().info("LLM initialised", provider=provider, model=model)
        _analysis_service = AnalysisService(
            section_analyser   = get_section_analyser(),
            synthesis_analyser = get_synthesis_analyser(),
            logger             = get_logger(),
        )
    return _analysis_service
