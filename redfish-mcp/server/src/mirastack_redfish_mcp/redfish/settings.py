"""Helpers for `@Redfish.Settings` write indirection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SettingsTarget:
    """Resolved settings endpoint for deferred apply resources."""

    settings_uri: str
    current_etag: str | None


def resolve_settings_target(resource: dict[str, Any]) -> SettingsTarget | None:
    """
    Resolve a SettingsObject URI from `@Redfish.Settings`.

    Returns None when the resource does not expose the annotation.
    """
    settings = resource.get("@Redfish.Settings")
    if not isinstance(settings, dict):
        return None
    settings_obj = settings.get("SettingsObject")
    if not isinstance(settings_obj, dict):
        return None
    uri = settings_obj.get("@odata.id")
    if not isinstance(uri, str) or not uri.strip():
        return None
    etag = settings.get("ETag")
    return SettingsTarget(settings_uri=uri, current_etag=etag if isinstance(etag, str) else None)
