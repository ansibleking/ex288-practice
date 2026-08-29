"""Async Redfish HTTP client with protocol-aware helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx2 as httpx

from mirastack_redfish_mcp.models import EndpointConfig
from mirastack_redfish_mcp.redfish.auth import AuthManager
from mirastack_redfish_mcp.redfish.errors import parse_redfish_error
from mirastack_redfish_mcp.redfish.registries import RegistryStore
from mirastack_redfish_mcp.redfish.tasks import task_uri_from_202, wait_for_task


class _RegistryRenderer:
    """Adapter used by parse_redfish_error."""

    def __init__(self, store: RegistryStore, client: RedfishClient) -> None:
        self._store = store
        self._client = client

    async def render_message(
        self, message_id: str, message_args: list[str] | None
    ) -> tuple[str, str | None] | None:
        return await self._store.render_message(
            message_id, message_args, get_json=self._client.get_json
        )


class RedfishClient:
    """Tenant-local client for one Redfish endpoint."""

    def __init__(
        self,
        endpoint: EndpointConfig,
        registry_store: RegistryStore,
        *,
        retries: int = 2,
        retry_backoff_sec: float = 0.7,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self._registry_store = registry_store
        self._auth = AuthManager(endpoint)
        self._client: httpx.AsyncClient | None = None
        self._etag_cache: dict[str, str] = {}
        self._retries = retries
        self._retry_backoff_sec = retry_backoff_sec
        self._transport = transport

    async def __aenter__(self) -> RedfishClient:
        verify_value: bool | str = self.endpoint.verify_ssl
        if self.endpoint.ca_bundle:
            verify_value = self.endpoint.ca_bundle
        self._client = httpx.AsyncClient(
            base_url=self.endpoint.base_url,
            timeout=self.endpoint.timeout_sec,
            verify=verify_value,
            headers={"Accept": "application/json", **self.endpoint.headers},
            transport=self._transport,
        )
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close network resources and delete any created Redfish session."""
        if self._client is None:
            return
        client = self._client
        self._client = None
        await self._auth.close(client)
        await client.aclose()

    def _resolve_uri(self, uri: str) -> str:
        uri = uri.strip()
        if uri.startswith("http://") or uri.startswith("https://"):
            base = urlparse(self.endpoint.base_url)
            target = urlparse(uri)
            if (base.scheme, base.netloc) != (target.scheme, target.netloc):
                raise ValueError(f"cross-host URI rejected: {uri}")
            if target.path:
                out = target.path
                if target.query:
                    out += f"?{target.query}"
                return out
        if not uri.startswith("/"):
            return f"/{uri}"
        return uri

    async def _request_with_retry(
        self,
        method: str,
        uri: str,
        *,
        json_body: Mapping[str, Any] | list[Any] | None = None,
        headers: Mapping[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> httpx.Response:
        client = self._client
        if client is None:
            raise RuntimeError("client is not opened; use 'async with RedfishClient(...)'")
        attempt = 0
        last_exc: Exception | None = None
        resolved_uri = self._resolve_uri(uri)

        while attempt <= self._retries:
            req_headers = dict(headers or {})
            if auth is None:
                dynamic_headers, basic_auth = await self._auth.ensure_headers(client)
                req_headers.update(dynamic_headers)
                auth_to_use = basic_auth
            else:
                auth_to_use = auth
            try:
                return await client.request(
                    method=method.upper(),
                    url=resolved_uri,
                    json=json_body,
                    headers=req_headers,
                    auth=auth_to_use,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt >= self._retries:
                    break
                await asyncio.sleep(self._retry_backoff_sec * (2**attempt))
                attempt += 1
        if last_exc is None:
            raise RuntimeError("request failed without explicit exception")
        raise last_exc

    @staticmethod
    def _extract_etag(response: httpx.Response, payload: Any) -> str | None:
        etag = response.headers.get("ETag") or response.headers.get("etag")
        if isinstance(etag, str) and etag.strip():
            return etag.strip()
        if isinstance(payload, dict):
            odata_etag = payload.get("@odata.etag")
            if isinstance(odata_etag, str) and odata_etag.strip():
                return odata_etag.strip()
        return None

    async def request_json(
        self,
        method: str,
        uri: str,
        *,
        json_body: Mapping[str, Any] | list[Any] | None = None,
        if_match: bool = False,
        wait_task: bool = False,
        task_timeout_sec: float = 300.0,
    ) -> dict[str, Any]:
        """Issue one JSON request with Redfish-aware error and task handling."""
        req_headers: dict[str, str] = {}
        resolved_uri = self._resolve_uri(uri)
        if if_match:
            etag = self._etag_cache.get(resolved_uri)
            if etag:
                req_headers["If-Match"] = etag

        response = await self._request_with_retry(
            method=method,
            uri=resolved_uri,
            json_body=json_body,
            headers=req_headers,
        )
        payload: Any
        if response.content:
            try:
                payload = response.json()
            except Exception:
                payload = {}
        else:
            payload = {}

        etag = self._extract_etag(response, payload)
        if etag is not None:
            self._etag_cache[resolved_uri] = etag

        if 200 <= response.status_code < 300:
            if response.status_code == 202 and wait_task:
                task_uri = task_uri_from_202(dict(response.headers), payload)
                if task_uri:
                    task_payload = await wait_for_task(
                        get_json=self.get_json, task_uri=task_uri, timeout_sec=task_timeout_sec
                    )
                    return {"accepted": True, "task_uri": task_uri, "task": task_payload}
            return payload if isinstance(payload, dict) else {"value": payload}

        renderer = _RegistryRenderer(self._registry_store, self)
        raise await parse_redfish_error(
            status_code=response.status_code,
            uri=resolved_uri,
            payload=payload,
            renderer=renderer,
        )

    async def get_json(self, uri: str) -> dict[str, Any]:
        return await self.request_json("GET", uri)

    async def post_json(
        self,
        uri: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        *,
        wait_task: bool = True,
    ) -> dict[str, Any]:
        return await self.request_json("POST", uri, json_body=body, wait_task=wait_task)

    async def patch_json(
        self,
        uri: str,
        body: Mapping[str, Any] | list[Any] | None = None,
        *,
        wait_task: bool = True,
        if_match: bool = True,
    ) -> dict[str, Any]:
        return await self.request_json(
            "PATCH",
            uri,
            json_body=body,
            if_match=if_match,
            wait_task=wait_task,
        )

    async def delete_json(self, uri: str, *, wait_task: bool = True) -> dict[str, Any]:
        return await self.request_json("DELETE", uri, wait_task=wait_task)
