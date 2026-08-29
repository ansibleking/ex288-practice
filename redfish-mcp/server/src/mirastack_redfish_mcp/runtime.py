"""Runtime container shared by MCP tools."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

from mirastack_redfish_mcp.config import load_config
from mirastack_redfish_mcp.models import AppConfig, EndpointConfig
from mirastack_redfish_mcp.redfish.capabilities import CapabilityCache
from mirastack_redfish_mcp.redfish.client import RedfishClient
from mirastack_redfish_mcp.redfish.registries import RegistryStore
from mirastack_redfish_mcp.safety import SafetyGate
from mirastack_redfish_mcp.schema.index import SchemaIndex
from mirastack_redfish_mcp.schema.resolver import UriResolver

LOGGER = logging.getLogger(__name__)
NO_ENDPOINTS_CONFIGURED_MESSAGE = (
    "No Redfish endpoints are configured. Set MIRASTACK_REDFISH_HOST, "
    "MIRASTACK_REDFISH_USERNAME, and MIRASTACK_REDFISH_PASSWORD (or "
    "MIRASTACK_REDFISH_PASSWORD_FILE), or provide MIRASTACK_REDFISH_ENDPOINTS. "
    "See the mockup quickstart: "
    "https://github.com/mirastacklabs-ai/mirastack-redfish-mcp#try-it-in-60-seconds-no-hardware"
)


class RedfishRuntime:
    """Holds immutable state and factories used by tool handlers."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self._warn_insecure_tls_endpoints()
        self.schema_index = self._load_schema_index(self.config.schema_index_path)
        self.uri_resolver = UriResolver(self.schema_index)
        self.registry_store = RegistryStore(self.schema_index.data)
        self.safety = SafetyGate(self.config)
        self.capabilities = CapabilityCache()

    @staticmethod
    def _load_schema_index(path: str) -> SchemaIndex:
        candidate = Path(path)
        if candidate.exists():
            return SchemaIndex.from_path(candidate)
        package_file = files("mirastack_redfish_mcp.data").joinpath("redfish_index.json.gz")
        payload = package_file.read_bytes()
        return SchemaIndex.from_bytes(payload, gzipped=True)

    def _warn_insecure_tls_endpoints(self) -> None:
        for endpoint in self.config.endpoints.values():
            if endpoint.verify_ssl:
                continue
            LOGGER.warning(
                "Endpoint '%s' has TLS certificate verification disabled (verify_ssl=false). "
                "Use only for controlled lab environments.",
                endpoint.name,
            )

    def _require_configured_endpoints(self) -> None:
        if not self.config.endpoints:
            raise ValueError(NO_ENDPOINTS_CONFIGURED_MESSAGE)

    def resolve_endpoint(self, endpoint_name: str | None) -> EndpointConfig:
        self._require_configured_endpoints()
        if endpoint_name is None:
            endpoint_name = self.config.default_endpoint or next(iter(self.config.endpoints))
        endpoint = self.config.endpoints.get(endpoint_name)
        if endpoint is None:
            raise KeyError(f"unknown endpoint: {endpoint_name}")
        return endpoint

    @asynccontextmanager
    async def client_for(self, endpoint_name: str | None = None) -> AsyncIterator[RedfishClient]:
        endpoint = self.resolve_endpoint(endpoint_name)
        client = RedfishClient(endpoint=endpoint, registry_store=self.registry_store)
        async with client:
            yield client
