"""Redfish message-registry loading and rendering."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

MessageLookup = Callable[[str], Awaitable[dict[str, Any]]]

MESSAGE_ID_RE = re.compile(r"^([A-Za-z0-9_]+)\.(\d+)\.(\d+)\.([A-Za-z0-9_]+)$")


@dataclass(frozen=True)
class RegistryMessage:
    """Distilled message template from a Redfish registry."""

    template: str
    resolution: str | None
    severity: str | None


def _substitute_message(template: str, args: list[str]) -> str:
    rendered = template
    for idx, arg in enumerate(args, start=1):
        rendered = rendered.replace(f"%{idx}", arg)
    return rendered


class RegistryStore:
    """Local-first message registry rendering with runtime fallback."""

    def __init__(self, local_catalog: dict[str, Any]) -> None:
        self._local: dict[tuple[str, str], dict[str, RegistryMessage]] = {}
        self._latest_versions: dict[str, str] = {}
        self._remote: dict[tuple[str, str], dict[str, RegistryMessage]] = {}
        self._locations: dict[tuple[str, str], str] = {}
        self._load_local(local_catalog)

    def _load_local(self, local_catalog: dict[str, Any]) -> None:
        registries = local_catalog.get("registries", {})
        if not isinstance(registries, dict):
            return
        for prefix, versions in registries.items():
            if not isinstance(versions, dict):
                continue
            sorted_versions = sorted(versions.keys(), key=_version_tuple)
            if sorted_versions:
                self._latest_versions[prefix] = sorted_versions[-1]
            for version, payload in versions.items():
                if not isinstance(payload, dict):
                    continue
                messages_payload = payload.get("messages", {})
                if not isinstance(messages_payload, dict):
                    continue
                bucket: dict[str, RegistryMessage] = {}
                for key, msg_payload in messages_payload.items():
                    if not isinstance(msg_payload, dict):
                        continue
                    template = str(msg_payload.get("Message", ""))
                    if not template:
                        continue
                    bucket[key] = RegistryMessage(
                        template=template,
                        resolution=(
                            str(msg_payload.get("Resolution"))
                            if msg_payload.get("Resolution") is not None
                            else None
                        ),
                        severity=(
                            str(
                                msg_payload.get("MessageSeverity")
                                or msg_payload.get("Severity")
                                or ""
                            )
                            or None
                        ),
                    )
                self._local[(prefix, version)] = bucket

    async def discover_remote_locations(self, get_json: MessageLookup) -> None:
        """Discover per-registry URIs from /redfish/v1/Registries."""
        collection = await get_json("/redfish/v1/Registries")
        members = collection.get("Members") if isinstance(collection, dict) else None
        if not isinstance(members, list):
            return
        for member in members:
            if not isinstance(member, dict):
                continue
            uri = member.get("@odata.id")
            if not isinstance(uri, str):
                continue
            payload = await get_json(uri)
            registry_name = payload.get("Registry")
            if not isinstance(registry_name, str):
                continue
            prefix, _, version = registry_name.partition(".")
            if not prefix or not version:
                continue
            locations = payload.get("Location")
            if not isinstance(locations, list):
                continue
            chosen: str | None = None
            for location in locations:
                if not isinstance(location, dict):
                    continue
                candidate = location.get("Uri")
                if isinstance(candidate, str):
                    chosen = candidate
                    break
            if chosen:
                self._locations[(prefix, version)] = chosen

    async def _load_remote_registry(
        self, prefix: str, version: str, get_json: MessageLookup
    ) -> dict[str, RegistryMessage] | None:
        cache_key = (prefix, version)
        if cache_key in self._remote:
            return self._remote[cache_key]
        uri = self._locations.get(cache_key)
        if uri is None:
            return None
        payload = await get_json(uri)
        messages = payload.get("Messages") if isinstance(payload, dict) else None
        if not isinstance(messages, dict):
            return None
        bucket: dict[str, RegistryMessage] = {}
        for key, msg_payload in messages.items():
            if not isinstance(msg_payload, dict):
                continue
            template = msg_payload.get("Message")
            if not isinstance(template, str):
                continue
            resolution = msg_payload.get("Resolution")
            severity = msg_payload.get("MessageSeverity") or msg_payload.get("Severity")
            bucket[str(key)] = RegistryMessage(
                template=template,
                resolution=str(resolution) if isinstance(resolution, str) else None,
                severity=str(severity) if isinstance(severity, str) else None,
            )
        self._remote[cache_key] = bucket
        return bucket

    async def render_message(
        self, message_id: str, message_args: list[str] | None, get_json: MessageLookup | None = None
    ) -> tuple[str, str | None] | None:
        """
        Render message text and resolution for a Redfish MessageId.

        MessageId format: RegistryPrefix.Major.Minor.MessageKey
        """
        match = MESSAGE_ID_RE.match(message_id.strip())
        if match is None:
            return None
        prefix = match.group(1)
        version = f"{match.group(2)}.{match.group(3)}.0"
        key = match.group(4)
        args = message_args or []

        rendered = self._render_from_bucket(self._local.get((prefix, version)), key, args)
        if rendered is not None:
            return rendered

        latest = self._latest_versions.get(prefix)
        if latest is not None:
            rendered = self._render_from_bucket(self._local.get((prefix, latest)), key, args)
            if rendered is not None:
                return rendered

        if get_json is not None:
            remote_bucket = await self._load_remote_registry(prefix, version, get_json)
            rendered = self._render_from_bucket(remote_bucket, key, args)
            if rendered is not None:
                return rendered
        return None

    @staticmethod
    def _render_from_bucket(
        bucket: dict[str, RegistryMessage] | None, key: str, args: list[str]
    ) -> tuple[str, str | None] | None:
        if bucket is None:
            return None
        msg = bucket.get(key)
        if msg is None:
            return None
        return (_substitute_message(msg.template, args), msg.resolution)


def _version_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    padded = (parts + ["0", "0", "0"])[:3]
    return (int(padded[0]), int(padded[1]), int(padded[2]))
