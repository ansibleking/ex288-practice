"""Redfish authentication helpers (session + basic)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx2 as httpx

from mirastack_redfish_mcp.models import AuthMode, EndpointConfig


@dataclass(slots=True)
class SessionAuthState:
    """Session token and URI to destroy it at shutdown."""

    token: str
    session_uri: str | None


class AuthManager:
    """Negotiates auth mode and returns request headers."""

    def __init__(self, endpoint: EndpointConfig) -> None:
        self._endpoint = endpoint
        self._session: SessionAuthState | None = None

    @property
    def basic_auth(self) -> tuple[str, str]:
        return (self._endpoint.username, self._endpoint.password)

    async def _create_session(self, client: httpx.AsyncClient) -> SessionAuthState:
        payload = {"UserName": self._endpoint.username, "Password": self._endpoint.password}
        response = await client.post("/redfish/v1/SessionService/Sessions", json=payload)
        response.raise_for_status()
        token = response.headers.get("X-Auth-Token") or response.headers.get("x-auth-token")
        if not token:
            raise RuntimeError("session creation succeeded but X-Auth-Token was missing")
        session_uri = response.headers.get("Location")
        if session_uri is None:
            try:
                body = response.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                odata_id = body.get("@odata.id")
                if isinstance(odata_id, str):
                    session_uri = odata_id
        return SessionAuthState(token=token, session_uri=session_uri)

    async def ensure_headers(
        self, client: httpx.AsyncClient
    ) -> tuple[dict[str, str], tuple[str, str] | None]:
        """
        Return per-request headers and optional basic auth tuple.

        In AUTO mode, session auth is preferred and basic auth is fallback.
        """
        mode = self._endpoint.auth_mode
        if mode is AuthMode.BASIC:
            return ({}, self.basic_auth)

        if self._session is None:
            try:
                self._session = await self._create_session(client)
            except Exception:
                if mode is AuthMode.SESSION:
                    raise
                return ({}, self.basic_auth)
        return ({"X-Auth-Token": self._session.token}, None)

    async def close(self, client: httpx.AsyncClient) -> None:
        """Destroy the Redfish session if one was created."""
        if self._session is None:
            return
        session_uri = self._session.session_uri
        token = self._session.token
        self._session = None
        if not session_uri:
            return
        try:
            await client.delete(session_uri, headers={"X-Auth-Token": token})
        except Exception:
            return
