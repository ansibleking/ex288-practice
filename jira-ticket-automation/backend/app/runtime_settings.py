from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings

VALID_PROVIDERS = {"onprem", "anthropic"}


def _override_path(settings: Settings) -> Path:
    # Lives next to the audit db in the same persistent ./data volume, so a
    # provider switch made in the running app survives a container restart
    # without needing to edit .env and redeploy.
    return Path(settings.database_path).parent / "llm_provider_override.json"


def get_provider_override(settings: Settings) -> str | None:
    path = _override_path(settings)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    provider = data.get("provider")
    return provider if provider in VALID_PROVIDERS else None


def set_provider_override(settings: Settings, provider: str | None) -> None:
    path = _override_path(settings)
    if provider is None:
        path.unlink(missing_ok=True)
        return
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}; expected 'onprem' or 'anthropic'")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": provider}))


def effective_provider(settings: Settings) -> str:
    return get_provider_override(settings) or settings.default_llm_provider.lower()
