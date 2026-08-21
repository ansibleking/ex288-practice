from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from tams_mcp.auth import TamsAuthManager
from tams_mcp.ssl_util import ssl_verify_setting


class TamsClient:
    def __init__(self, base_url: str, auth: TamsAuthManager, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout = timeout
        self.auth.client = self

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        auth_header = self.auth.get_authorization_header()
        if auth_header:
            headers["Authorization"] = auth_header
        return headers

    async def post_raw(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        async with httpx.AsyncClient(timeout=self.timeout, verify=ssl_verify_setting()) as client:
            response = await client.post(
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
            )
            response.raise_for_status()
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
    ) -> Any:
        await self.auth.ensure_login()
        return await self.post_raw(path, params=params, json_body=json_body)

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        await self.auth.ensure_login()
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        async with httpx.AsyncClient(timeout=self.timeout, verify=ssl_verify_setting()) as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            if response.content:
                return response.json()
            return {"status": response.status_code}
