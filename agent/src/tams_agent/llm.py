from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from tams_agent.llm_profiles import LlmOverrides, resolve_active_overrides
from tams_agent.ssl_util import make_sync_http_client, ssl_verify_setting


@dataclass
class ActiveLlmConfig:
    provider: str
    base_url: str | None
    model: str
    api_key: str
    verify_ssl: bool | str
    timeout: float
    max_tokens: int = 4096
    profile: str | None = None


_active: LlmOverrides | None = None


def set_llm_overrides(overrides: LlmOverrides | None) -> None:
    global _active
    _active = overrides


def _default_model(provider: str, fallback: str) -> str:
    if provider == "anthropic":
        return fallback if fallback != "gpt-4o" else "claude-sonnet-4-20250514"
    return fallback


def _resolve_api_key(provider: str, merged: LlmOverrides) -> str:
    if merged.api_key:
        return merged.api_key
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY", "")
    return (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ONPREM_LLM_API_KEY")
        or os.getenv("LLM_API_KEY")
        or ("local" if merged.base_url else "")
    )


def get_active_config(default_model: str = "gpt-4o") -> ActiveLlmConfig:
    merged = resolve_active_overrides(_active)

    provider = (merged.provider or os.getenv("AGENT_LLM_PROVIDER") or "openai").lower()
    base_url = merged.base_url
    if not base_url and provider == "anthropic":
        base_url = os.getenv("ANTHROPIC_BASE_URL")

    model = merged.model or _default_model(provider, default_model)
    api_key = _resolve_api_key(provider, merged)

    if merged.verify_ssl is not None:
        verify_ssl: bool | str = merged.verify_ssl
    else:
        verify_ssl = ssl_verify_setting()

    timeout = merged.timeout if merged.timeout is not None else 120.0
    max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))

    return ActiveLlmConfig(
        provider=provider,
        base_url=base_url.rstrip("/") if base_url else None,
        model=model,
        api_key=api_key,
        verify_ssl=verify_ssl,
        timeout=timeout,
        max_tokens=max_tokens,
        profile=merged.profile,
    )


def llm_base_url() -> str | None:
    return get_active_config().base_url


def llm_model(default: str = "gpt-4o") -> str:
    return get_active_config(default_model=default).model


def create_openai_client():
    from openai import OpenAI

    cfg = get_active_config()
    if cfg.provider == "anthropic":
        raise RuntimeError("create_openai_client() called while provider=anthropic")

    if not cfg.api_key and not cfg.base_url:
        raise RuntimeError(
            "LLM not configured. Use --llm PROFILE, --model/--llm-url flags, or set ONPREM_LLM_* in .env."
        )

    kwargs: dict[str, Any] = {
        "api_key": cfg.api_key or "local",
        "http_client": make_sync_http_client(timeout=cfg.timeout, verify=cfg.verify_ssl),
    }
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    return OpenAI(**kwargs)


def create_anthropic_client():
    from anthropic import Anthropic

    cfg = get_active_config(default_model="claude-sonnet-4-20250514")
    if cfg.provider != "anthropic":
        raise RuntimeError("create_anthropic_client() called while provider!=anthropic")

    if not cfg.api_key:
        raise RuntimeError(
            "Anthropic not configured. Set ANTHROPIC_API_KEY in .env, --llm-key, or profile api_key."
        )

    kwargs: dict[str, Any] = {
        "api_key": cfg.api_key,
        "http_client": make_sync_http_client(timeout=cfg.timeout, verify=cfg.verify_ssl),
    }
    if cfg.base_url:
        kwargs["base_url"] = cfg.base_url
    return Anthropic(**kwargs)


def describe_llm_target() -> str:
    cfg = get_active_config()
    profile_note = f"profile={cfg.profile}, " if cfg.profile else ""

    if cfg.provider == "anthropic":
        where = cfg.base_url or "api.anthropic.com"
        return f"{profile_note}Anthropic at {where} (model={cfg.model})"

    verify_note = "verify=off" if cfg.verify_ssl is False else f"verify={cfg.verify_ssl}"
    if cfg.base_url:
        return f"{profile_note}OpenAI-compatible at {cfg.base_url} (model={cfg.model}, {verify_note})"
    return f"{profile_note}OpenAI cloud (model={cfg.model})"
