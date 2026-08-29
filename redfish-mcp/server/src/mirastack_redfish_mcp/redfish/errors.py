"""Error types and extraction for Redfish responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class RegistryRenderer(Protocol):
    """Protocol for rendering MessageIds through local/remote registries."""

    async def render_message(
        self, message_id: str, message_args: list[str] | None
    ) -> tuple[str, str | None] | None:
        """Return (rendered_message, resolution) if known."""


@dataclass(frozen=True)
class ExtendedMessage:
    """One `@Message.ExtendedInfo` entry."""

    message_id: str
    message: str | None
    severity: str | None
    resolution: str | None
    related_properties: list[str]
    message_args: list[str]


class RedfishHTTPError(RuntimeError):
    """Raised for non-2xx responses from Redfish services."""

    def __init__(
        self,
        *,
        status_code: int,
        uri: str,
        code: str | None,
        message: str,
        extended: list[ExtendedMessage],
    ) -> None:
        self.status_code = status_code
        self.uri = uri
        self.code = code
        self.extended = extended
        super().__init__(f"Redfish {status_code} at {uri}: {message}")


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


async def parse_redfish_error(
    *,
    status_code: int,
    uri: str,
    payload: Any,
    renderer: RegistryRenderer | None = None,
) -> RedfishHTTPError:
    """Parse a Redfish error payload into a typed exception."""
    code: str | None = None
    message = f"HTTP {status_code}"
    extended: list[ExtendedMessage] = []

    if isinstance(payload, dict):
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            code = str(error_obj.get("code")) if error_obj.get("code") is not None else None
            if isinstance(error_obj.get("message"), str):
                message = str(error_obj["message"])
            extended_info = error_obj.get("@Message.ExtendedInfo")
            if isinstance(extended_info, list):
                for item in extended_info:
                    if not isinstance(item, dict):
                        continue
                    msg_id = str(item.get("MessageId", ""))
                    msg = item.get("Message")
                    rendered_resolution = item.get("Resolution")
                    if renderer is not None and msg_id:
                        rendered = await renderer.render_message(
                            msg_id, _coerce_string_list(item.get("MessageArgs"))
                        )
                        if rendered is not None:
                            msg, rendered_resolution = rendered
                    extended.append(
                        ExtendedMessage(
                            message_id=msg_id,
                            message=str(msg) if msg is not None else None,
                            severity=(
                                str(item.get("MessageSeverity"))
                                if item.get("MessageSeverity") is not None
                                else None
                            ),
                            resolution=(
                                str(rendered_resolution)
                                if rendered_resolution is not None
                                else None
                            ),
                            related_properties=_coerce_string_list(item.get("RelatedProperties")),
                            message_args=_coerce_string_list(item.get("MessageArgs")),
                        )
                    )
                if extended:
                    message = (
                        "; ".join(
                            part for part in [extended[0].message, extended[0].resolution] if part
                        )
                        or message
                    )

    return RedfishHTTPError(
        status_code=status_code,
        uri=uri,
        code=code,
        message=message,
        extended=extended,
    )
