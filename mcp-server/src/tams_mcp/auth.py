from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import msal

from tams_mcp.config import get_settings
from tams_mcp.context import build_login_payload, merge_report_scope, merge_with_login

if TYPE_CHECKING:
    from tams_mcp.tams_client import TamsClient

AuthMode = Literal["tams_login", "client_credentials", "device_code", "bearer_token", "none"]


@dataclass
class AuthConfig:
    mode: AuthMode = "tams_login"
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    scope: str = ""
    static_token: str = ""


def _extract_token(payload: dict[str, Any]) -> str | None:
    for key in ("token", "accessToken", "access_token", "jwt", "bearerToken", "authToken"):
        value = payload.get(key)
        if value:
            return str(value)
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _extract_token(nested)
    return None


def _validate_login_response(result: Any) -> None:
    if not isinstance(result, dict):
        return

    invalid_flags = [
        result.get("isValid") is False,
        result.get("result") is False,
        str(result.get("l_LicenseStatus", "")).lower() == "false",
    ]
    if any(invalid_flags):
        message = (
            result.get("l_ErrorText")
            or result.get("errorMsg")
            or result.get("message")
            or result
        )
        raise RuntimeError(f"TAMS login failed (GetLoginDetails): {message}")


class TamsAuthManager:
    """Handles Connect_API login and optional Entra bearer tokens."""

    def __init__(self, config: AuthConfig, client: TamsClient | None = None) -> None:
        self.config = config
        self.client = client
        self._entra_token: str | None = None
        self._login_context: dict[str, Any] | None = None

    async def ensure_login(self) -> dict[str, Any]:
        if self._login_context is not None:
            return self._login_context

        settings = get_settings()

        if settings.tams_access_token or (self.config.mode == "bearer_token" and self.config.static_token):
            token = settings.tams_access_token or self.config.static_token
            self._login_context = {"mode": "bearer_token", "token": token}
            return self._login_context

        if self.config.mode in {"client_credentials", "device_code"}:
            self._login_context = {"mode": self.config.mode, "token": self._get_entra_token()}
            return self._login_context

        if self.config.mode == "none":
            self._login_context = {"login": build_login_payload(settings)}
            return self._login_context

        if not settings.tams_username or not settings.tams_password:
            raise RuntimeError(
                "TAMS credentials missing. Set TAMS_USERNAME and TAMS_PASSWORD in .env, "
                "or TAMS_ACCESS_TOKEN from an authenticated browser session."
            )

        if self.client is None:
            raise RuntimeError("TAMS client is required for login")

        payload = build_login_payload(settings)
        result = await self.client.post_raw("/login/GetLoginDetails", json_body=payload)
        _validate_login_response(result)

        token = _extract_token(result) if isinstance(result, dict) else None
        self._login_context = {
            "mode": "tams_login",
            "login": payload,
            "profile": result,
            "token": token,
        }
        return self._login_context

    def enrich_body(self, body: dict[str, Any] | None, *, body_kind: str = "report") -> dict[str, Any]:
        body = dict(body or {})
        if body_kind == "none":
            return body

        login = (self._login_context or {}).get("login") or build_login_payload()
        if body_kind == "login":
            return merge_with_login(login, body)

    def get_authorization_header(self) -> str | None:
        settings = get_settings()
        if settings.tams_access_token:
            return f"Bearer {settings.tams_access_token}"
        if self.config.mode == "bearer_token" and self.config.static_token:
            return f"Bearer {self.config.static_token}"
        if self._entra_token:
            return f"Bearer {self._entra_token}"
        if self._login_context and self._login_context.get("token"):
            return f"Bearer {self._login_context['token']}"
        return None

    def _get_entra_token(self) -> str:
        if self._entra_token:
            return self._entra_token

        authority = f"https://login.microsoftonline.com/{self.config.tenant_id}"
        scopes = [self.config.scope] if self.config.scope else []

        if self.config.mode == "client_credentials":
            app = msal.ConfidentialClientApplication(
                self.config.client_id,
                authority=authority,
                client_credential=self.config.client_secret,
            )
            result = app.acquire_token_for_client(scopes=scopes)
        else:
            app = msal.PublicClientApplication(self.config.client_id, authority=authority)
            flow = app.initiate_device_flow(scopes=scopes)
            if "user_code" not in flow:
                raise RuntimeError(f"Device code flow failed: {flow}")
            print(flow["message"], file=sys.stderr)
            result = app.acquire_token_by_device_flow(flow)

        if "access_token" not in result:
            raise RuntimeError(f"Token acquisition failed: {result.get('error_description', result)}")

        self._entra_token = result["access_token"]
        return self._entra_token
