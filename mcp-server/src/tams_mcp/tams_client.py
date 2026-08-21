from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from tams_mcp.auth import TamsAuthManager
from tams_mcp.config import get_settings
from tams_mcp.ssl_util import ssl_verify_setting


class TamsApiError(RuntimeError):
    pass


class TamsClient:
    def __init__(self, base_url: str, auth: TamsAuthManager, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout = timeout
        self.auth.client = self
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self.timeout,
                verify=ssl_verify_setting(),
                follow_redirects=True,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        auth_header = self.auth.get_authorization_header()
        if auth_header:
            headers["Authorization"] = auth_header

        settings = get_settings()
        if settings.tams_session_cookie:
            headers["Cookie"] = settings.tams_session_cookie

        return headers

    def _raise_for_status(self, response: httpx.Response, *, path: str) -> None:
        if response.status_code == 401:
            cookie_hint = ""
            if not get_settings().tams_session_cookie and not get_settings().tams_access_token:
                cookie_hint = (
                    " Also try TAMS_ACCESS_TOKEN or TAMS_SESSION_COOKIE from browser DevTools "
                    "after logging into attendance.emaratech.ae."
                )
            raise TamsApiError(
                "TAMS API returned 401 Unauthorized for "
                f"{path}. Check TAMS_USERNAME/TAMS_PASSWORD and TAMS_AUTH_* scope fields in .env."
                + cookie_hint
            )
        if response.status_code in {400, 422}:
            detail = response.text.strip()[:800] or response.reason_phrase
            raise TamsApiError(
                f"TAMS API returned {response.status_code} for {path}: {detail}"
            )
        response.raise_for_status()

    async def post_raw(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        client = await self._get_http()
        response = await client.post(
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
        )
        self._raise_for_status(response, path=path)
        if response.content:
            try:
                return response.json()
            except ValueError:
                return {"raw": response.text}
        return {"status": response.status_code}

    async def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        body_kind: str = "report",
    ) -> Any:
        await self.auth.ensure_login()
        body = self.auth.enrich_body(json_body, body_kind=body_kind)
        return await self.post_raw(path, params=params, json_body=body)

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        await self.auth.ensure_login()
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        client = await self._get_http()
        response = await client.get(url, headers=self._headers(), params=params)
        self._raise_for_status(response, path=path)
        if response.content:
            return response.json()
        return {"status": response.status_code}

    def cookie_count(self) -> int:
        if self._http is None:
            return 0
        return len(self._http.cookies)
