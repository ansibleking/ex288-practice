from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import msal

from tams_mcp.config import get_settings
from tams_mcp.context import build_login_payload

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

        if self.config.mode == "bearer_token":
            self._login_context = {"mode": "bearer_token"}
            return self._login_context

        if self.config.mode in {"client_credentials", "device_code"}:
            self._login_context = {"mode": self.config.mode, "token": self._get_entra_token()}
            return self._login_context

        if self.config.mode == "none":
            self._login_context = {}
            return self._login_context

        settings = get_settings()
        if not settings.tams_username or not settings.tams_password:
            raise RuntimeError("TAMS_USERNAME and TAMS_PASSWORD are required for tams_login mode")

        if self.client is None:
            raise RuntimeError("TAMS client is required for login")

        payload = build_login_payload(settings)
        result = await self.client.post_raw("/login/GetLoginDetails", json_body=payload)
        self._login_context = {"mode": "tams_login", "login": payload, "profile": result}
        return self._login_context

    def get_authorization_header(self) -> str | None:
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
