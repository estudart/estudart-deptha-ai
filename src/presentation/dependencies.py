"""Singletons — all dependency instances are created and held here."""

import json
import os

from openai import OpenAI

from src.application.entities.analysis_result import AnalysisResult
from src.application.services.analysis_service import AnalysisService
from src.infrastructure.dicom_reader import DicomReader
from src.infrastructure.image_encoder import ImageEncoder
from src.infrastructure.logger import Logger
from src.infrastructure.openai_client import OpenAIClient

_logger: Logger | None = None
_openai_client: OpenAIClient | None = None
_analysis_service: AnalysisService | None = None


def get_logger() -> Logger:
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger


def get_openai_client() -> OpenAIClient:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAIClient(
            client=OpenAI(api_key=os.environ["OPENAI_API_KEY"]),
            output_schema=json.dumps(AnalysisResult.model_json_schema(), indent=2),
        )
    return _openai_client


def get_analysis_service() -> AnalysisService:
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService(
            dicom_reader=DicomReader(),
            image_encoder=ImageEncoder(),
            openai_client=get_openai_client(),
            logger=get_logger(),
        )
    return _analysis_service
