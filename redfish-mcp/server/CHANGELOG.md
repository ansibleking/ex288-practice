# Changelog

All notable changes to this project are documented in this file.

## 0.1.2 - 2026-08-12

- Treated a missing `MIRASTACK_REDFISH_ENDPOINTS` file as discovery mode instead of a fatal startup error, so container platforms that inject a placeholder endpoints path can complete MCP inspection.
- Kept malformed, unreadable, and partially configured endpoint sources as hard startup failures.
- Documented that a generated `uv sync` container build installs the console script under `/app/.venv/bin`, which the launcher must reference by absolute path.
- Extended `scripts/check_versions.py` to cover `__init__.py` and the `server.json` OCI image tag, and wired it into `make gate`.

## 0.1.1 - 2026-08-11

- Allowed startup with zero configured endpoints so MCP scanners can run initialize/tools-list without credentials.
- Kept strict validation for partial or malformed endpoint configuration while preserving read-only tool registration behavior.
- Added discovery-mode startup warning on stderr and endpoint-required invocation errors for BMC-connected tools.
- Added tests for empty-env config loading, stdio discovery parity, and zero-endpoint tool behavior.

## 0.1.0 - 2026-08-11

- Renamed the distribution and Python module to `mirastack-redfish-mcp` / `mirastack_redfish_mcp`.
- Hardened public documentation and examples for mirror-safe publishing.
- Added governed release and registry metadata for GitLab-driven publishing.
- Updated write-tier governance, TLS verification documentation, and mirror contribution policy.
