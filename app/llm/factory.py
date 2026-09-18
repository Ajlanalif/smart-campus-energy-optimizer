"""Factory for selecting the LLM provider based on environment configuration."""
from __future__ import annotations

import logging
import os

from app.llm.base import LLMProvider
from app.llm.provider import GeminiProvider, StaticProvider

logger = logging.getLogger("gridwise.llm.factory")


def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider.

    Honours LLM_PROVIDER env var. Defaults to Gemini if unset.
    """
    provider_name = (os.environ.get("LLM_PROVIDER") or "gemini").lower().strip()

    if provider_name == "gemini":
        logger.info("Using Gemini LLM provider")
        return GeminiProvider()
    if provider_name == "static":
        # Used by tests; payload is supplied via STATIC_LLM_PAYLOAD env var (JSON string).
        import json

        raw = os.environ.get("STATIC_LLM_PAYLOAD", '{"directives": []}')
        payload = json.loads(raw)
        return StaticProvider(payload=payload, model_name="static")
    raise ValueError(f"Unknown LLM_PROVIDER: {provider_name!r}")
