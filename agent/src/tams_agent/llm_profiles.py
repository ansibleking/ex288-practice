from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class LlmOverrides:
    profile: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    verify_ssl: bool | str | None = None
    timeout: float | None = None


def _profiles_paths() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.getenv("LLM_PROFILES_FILE")
    if env_path:
        candidates.append(Path(env_path))

    for base in (Path.cwd(), Path("/app"), Path(__file__).resolve().parents[3]):
        candidates.extend([base / "llm-profiles.json", base / "config" / "llm-profiles.json"])

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def load_profiles_file() -> dict[str, Any]:
    for path in _profiles_paths():
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return {"default": None, "profiles": {}}


def list_profile_names() -> list[str]:
    return sorted(load_profiles_file().get("profiles", {}).keys())


def resolve_profile(name: str) -> dict[str, Any]:
    profiles = load_profiles_file().get("profiles", {})
    if name not in profiles:
        available = ", ".join(sorted(profiles.keys())) or "(none)"
        raise ValueError(f"Unknown LLM profile '{name}'. Available: {available}")
    return dict(profiles[name])


def merge_overrides(*sources: LlmOverrides | None) -> LlmOverrides:
    merged = LlmOverrides()
    for source in sources:
        if source is None:
            continue
        for key in merged.__dataclass_fields__:
            value = getattr(source, key)
            if value is not None:
                setattr(merged, key, value)
    return merged


def overrides_from_env() -> LlmOverrides:
    verify = os.getenv("ONPREM_LLM_VERIFY_SSL") or os.getenv("LLM_VERIFY_SSL")
    verify_ssl: bool | str | None = None
    if verify is not None:
        verify_ssl = verify.strip().lower() not in {"0", "false", "no", "off"}

    timeout_raw = os.getenv("LLM_TIMEOUT") or os.getenv("ONPREM_LLM_TIMEOUT")
    timeout = float(timeout_raw) if timeout_raw else None

    return LlmOverrides(
        profile=os.getenv("LLM_PROFILE") or os.getenv("TAMS_AGENT_LLM"),
        provider=os.getenv("AGENT_LLM_PROVIDER"),
        base_url=os.getenv("ONPREM_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL"),
        model=os.getenv("ONPREM_LLM_MODEL") or os.getenv("AGENT_MODEL") or os.getenv("LLM_MODEL"),
        api_key=os.getenv("OPENAI_API_KEY") or os.getenv("ONPREM_LLM_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
        verify_ssl=verify_ssl,
        timeout=timeout,
    )


def overrides_from_profile(profile_name: str) -> LlmOverrides:
    profile = resolve_profile(profile_name)
    verify = profile.get("verify_ssl")
    if isinstance(verify, bool):
        verify_ssl: bool | str | None = verify
    elif verify is None:
        verify_ssl = None
    else:
        verify_ssl = str(verify).lower() not in {"0", "false", "no", "off"}

    timeout = profile.get("timeout")
    return LlmOverrides(
        profile=profile_name,
        provider=profile.get("provider"),
        base_url=profile.get("base_url") or profile.get("url"),
        model=profile.get("model"),
        api_key=profile.get("api_key"),
        verify_ssl=verify_ssl,
        timeout=float(timeout) if timeout is not None else None,
    )


def _shared_secrets(profile_overrides: LlmOverrides, cli: LlmOverrides | None) -> LlmOverrides:
    env = overrides_from_env()
    provider = (
        (cli.provider if cli and cli.provider else None)
        or profile_overrides.provider
        or env.provider
        or "openai"
    ).lower()

    api_key = profile_overrides.api_key or (cli.api_key if cli and cli.api_key else None)
    if not api_key:
        if provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
        else:
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("ONPREM_LLM_API_KEY") or os.getenv("LLM_API_KEY")

    return LlmOverrides(
        api_key=api_key,
        verify_ssl=env.verify_ssl if profile_overrides.verify_ssl is None else None,
        timeout=env.timeout if profile_overrides.timeout is None else None,
    )


def resolve_active_overrides(cli: LlmOverrides | None = None) -> LlmOverrides:
    env = overrides_from_env()
    data = load_profiles_file()

    profile_name = (cli.profile if cli and cli.profile else None) or env.profile or data.get("default")

    if profile_name:
        profile_overrides = overrides_from_profile(profile_name)
        # Profile controls provider/url/model; .env only supplies shared secrets unless CLI overrides.
        return merge_overrides(profile_overrides, _shared_secrets(profile_overrides, cli), cli)

    return merge_overrides(env, cli)
