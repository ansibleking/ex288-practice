"""URI-template resolution against distilled Redfish schema index."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mirastack_redfish_mcp.schema.index import SchemaIndex


@dataclass(frozen=True)
class UriMatch:
    """Resolution result for an `@odata.id` URI."""

    resource_type: str
    template: str
    deprecated_template: bool


def _template_to_regex(template: str) -> re.Pattern[str]:
    escaped = re.escape(template.rstrip("/"))
    escaped = re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", escaped)
    return re.compile(rf"^{escaped}/?$")


class UriResolver:
    """Matches runtime URIs against schema `uris` template arrays."""

    def __init__(self, index: SchemaIndex) -> None:
        self._patterns: list[tuple[re.Pattern[str], UriMatch]] = []
        for resource_type, info in index.resource_types.items():
            for template in info.uris:
                self._patterns.append(
                    (_template_to_regex(template), UriMatch(resource_type, template, False))
                )
            for template in info.uris_deprecated:
                self._patterns.append(
                    (_template_to_regex(template), UriMatch(resource_type, template, True))
                )

    def resolve(self, uri: str) -> UriMatch | None:
        path = uri.split("?", 1)[0]
        path = path.rstrip("/")
        if path == "":
            path = "/"
        for pattern, match in self._patterns:
            if pattern.match(path):
                return match
        # Some runtime-only resources are linked from annotations, not `uris` arrays.
        if path.endswith("/Settings"):
            return UriMatch("Settings", "/.../Settings", True)
        if path.endswith("ActionInfo"):
            return UriMatch("ActionInfo", "/.../ActionInfo", True)
        # OEM and implementation-defined subresources often sit outside DSP8010 `uris`.
        if "/Oem/" in path or path.endswith("/SD") or "/OperatingSystem/Containers/" in path:
            return UriMatch("Resource", "/.../Resource", True)
        return None
