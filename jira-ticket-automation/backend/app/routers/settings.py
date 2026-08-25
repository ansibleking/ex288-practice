from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm import get_llm_client_for_provider
from app.runtime_settings import effective_provider, set_provider_override

router = APIRouter(prefix="/api/settings/llm", tags=["settings"])

# Long enough for a real generation call to prove the endpoint actually
# works (not just that it accepts a connection), short enough that a
# clearly-unreachable endpoint doesn't leave the Test button hanging for the
# full multi-minute timeout diagram generation gets.
TEST_TIMEOUT_SECONDS = 20.0


class ProviderStatus(BaseModel):
    configured: bool


class LlmSettingsResponse(BaseModel):
    provider: str
    default_provider: str
    override_active: bool
    onprem: ProviderStatus
    anthropic: ProviderStatus


def _looks_like_real_anthropic_key(key: str) -> bool:
    # .env.example ships "replace-with-anthropic-api-key" as a placeholder --
    # a plain non-empty check would report that as "configured" and let
    # someone switch to (or test) a provider that can only fail. Real
    # Anthropic API keys always start with this prefix.
    return key.startswith("sk-ant-")


def _status(settings: Settings) -> LlmSettingsResponse:
    current = effective_provider(settings)
    default = settings.default_llm_provider.lower()
    return LlmSettingsResponse(
        provider=current,
        default_provider=default,
        override_active=current != default,
        onprem=ProviderStatus(configured=bool(settings.onprem_llm_base_url)),
        anthropic=ProviderStatus(configured=_looks_like_real_anthropic_key(settings.anthropic_api_key)),
    )


@router.get("", response_model=LlmSettingsResponse)
async def get_llm_settings(settings: Settings = Depends(get_settings)) -> LlmSettingsResponse:
    return _status(settings)


class SetProviderRequest(BaseModel):
    # null clears the override and reverts to DEFAULT_LLM_PROVIDER from .env
    provider: str | None


@router.put("", response_model=LlmSettingsResponse)
async def set_llm_provider(
    body: SetProviderRequest, settings: Settings = Depends(get_settings)
) -> LlmSettingsResponse:
    try:
        set_provider_override(settings, body.provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _status(settings)


class TestProviderRequest(BaseModel):
    provider: str


class TestProviderResponse(BaseModel):
    ok: bool
    latency_ms: int | None
    error: str | None


class _PingResult(BaseModel):
    ok: bool


@router.post("/test", response_model=TestProviderResponse)
async def test_llm_provider(
    body: TestProviderRequest, settings: Settings = Depends(get_settings)
) -> TestProviderResponse:
    try:
        client = get_llm_client_for_provider(settings, body.provider, timeout=TEST_TIMEOUT_SECONDS)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    started = time.monotonic()
    try:
        result = await client.parse(
            system="Reply with ok set to true.", user_content="ping", output_model=_PingResult
        )
        return TestProviderResponse(
            ok=bool(result.ok), latency_ms=int((time.monotonic() - started) * 1000), error=None
        )
    except Exception as exc:  # a connectivity/credentials probe reports every failure mode, never crashes
        return TestProviderResponse(
            ok=False, latency_ms=int((time.monotonic() - started) * 1000), error=str(exc)
        )
    finally:
        aclose = getattr(client, "aclose", None)
        if aclose is not None:
            await aclose()
