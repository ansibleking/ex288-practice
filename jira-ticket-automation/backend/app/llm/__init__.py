from __future__ import annotations

from app.config import Settings
from app.llm.anthropic_client import AnthropicStructuredClient
from app.llm.base import StructuredLLMClient
from app.llm.onprem_client import OnPremLLMError, OnPremStructuredClient

__all__ = [
    "StructuredLLMClient",
    "AnthropicStructuredClient",
    "OnPremStructuredClient",
    "OnPremLLMError",
    "get_llm_client",
]


def get_llm_client(settings: Settings) -> StructuredLLMClient:
    provider = settings.default_llm_provider.lower()
    if provider == "onprem":
        return OnPremStructuredClient(settings)
    if provider == "anthropic":
        return AnthropicStructuredClient(settings)
    raise ValueError(
        f"Unknown DEFAULT_LLM_PROVIDER {settings.default_llm_provider!r}; expected 'anthropic' or 'onprem'"
    )
