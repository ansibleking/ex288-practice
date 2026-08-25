from __future__ import annotations

from app.config import Settings
from app.llm.anthropic_client import AnthropicStructuredClient
from app.llm.base import StructuredLLMClient
from app.llm.onprem_client import OnPremLLMError, OnPremStructuredClient
from app.runtime_settings import effective_provider

__all__ = [
    "StructuredLLMClient",
    "AnthropicStructuredClient",
    "OnPremStructuredClient",
    "OnPremLLMError",
    "get_llm_client",
    "get_llm_client_for_provider",
]


def get_llm_client_for_provider(
    settings: Settings, provider: str, *, timeout: float | None = None
) -> StructuredLLMClient:
    provider = provider.lower()
    if provider == "onprem":
        return OnPremStructuredClient(settings, timeout=timeout)
    if provider == "anthropic":
        return AnthropicStructuredClient(settings, timeout=timeout)
    raise ValueError(f"Unknown LLM provider {provider!r}; expected 'anthropic' or 'onprem'")


def get_llm_client(settings: Settings, *, timeout: float | None = None) -> StructuredLLMClient:
    # Respects a live provider switch made via /api/settings/llm (stored in
    # runtime_settings) over the .env DEFAULT_LLM_PROVIDER, so switching
    # providers in the running app takes effect on the very next call --
    # no restart needed.
    return get_llm_client_for_provider(settings, effective_provider(settings), timeout=timeout)
