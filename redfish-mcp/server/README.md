# MIRASTACK Redfish MCP Server

> Governed MCP server for DMTF Redfish-compliant BMCs — iDRAC, iLO, XCC,
> OpenBMC and compatible implementations. **Read-only by default**: mutating
> tools are not registered unless you explicitly raise the write mode, and
> every mutation is a dry-run until confirmed.
>
> Built by [MIRASTACK LABS](https://mirastacklabs.ai). Apache-2.0.

<!-- mcp-name: ai.mirastacklabs/mirastack-redfish-mcp -->

[![mirastack-redfish-mcp MCP server](https://glama.ai/mcp/servers/mirastacklabs-ai/mirastack-redfish-mcp/badges/card.svg)](https://glama.ai/mcp/servers/mirastacklabs-ai/mirastack-redfish-mcp)

[![mirastack-redfish-mcp MCP server](https://glama.ai/mcp/servers/mirastacklabs-ai/mirastack-redfish-mcp/badges/score.svg)](https://glama.ai/mcp/servers/mirastacklabs-ai/mirastack-redfish-mcp)

## Highlights

- MCP `stdio` and `streamable-http` transports via the official Python MCP SDK.
- Distilled schema metadata from [DMTF Redfish-Publications](https://github.com/DMTF/Redfish-Publications), pinned to release `2026.1`.
- Protocol-correct Redfish behavior: session auth, ETag/`If-Match`, `202` task polling, and registry-backed error rendering.
- Safe write controls: tiered registration plus dry-run-first confirmations.

## Why this exists

A BMC is a pre-OS, out-of-band control plane with authority above normal host-level root access. Giving an autonomous agent BMC access without strong guardrails creates immediate blast-radius risk across power, boot, firmware, and account boundaries. This server forces dangerous actions behind deliberate write-mode elevation, and keeps every mutation dry-run by default so intent can be reviewed before application. The result is a governed operational interface rather than an always-armed remote control. The model can still move fast on diagnostics, but privilege transitions become explicit and auditable.

## Installation

```bash
pip install mirastack-redfish-mcp
```

## Try it in 60 seconds (no hardware)

Run a local DMTF mockup, start the MCP server in read-only mode, and call a read tool:

```bash
docker compose -f examples/mockup/docker-compose.yml up -d
export MIRASTACK_REDFISH_HOST="http://127.0.0.1:18000"
export MIRASTACK_REDFISH_USERNAME="<bmc-username>"
export MIRASTACK_REDFISH_PASSWORD="<bmc-password>"
export MIRASTACK_REDFISH_WRITE_MODE="off"
mirastack-redfish-mcp --transport stdio
```

Example tool call:

```json
{"tool":"service_info","arguments":{}}
```

Expected output shape:

```json
{
  "endpoint": "default",
  "service_root": {
    "@odata.id": "/redfish/v1"
  },
  "capabilities": {
    "redfish_version": "..."
  }
}
```

### Discovery mode

The server also starts with **zero endpoint credentials** and still serves read-only
tool discovery (for MCP scanner validation and metadata indexing). In this mode,
schema/corpus-backed tools continue to work, while BMC-connected tools return a
configuration error that names the required environment variables:
`MIRASTACK_REDFISH_HOST`, `MIRASTACK_REDFISH_USERNAME`, and
`MIRASTACK_REDFISH_PASSWORD` (or `MIRASTACK_REDFISH_PASSWORD_FILE`), or
`MIRASTACK_REDFISH_ENDPOINTS` for multi-endpoint setup.

Discovery mode also covers a **missing endpoints file**. If `MIRASTACK_REDFISH_ENDPOINTS`
points at a path that does not exist - which is how container platforms and MCP directory
scanners inject a placeholder - the server logs a warning naming that path on stderr and
starts with zero endpoints. A file that *does* exist but cannot be read or parsed remains a
hard startup failure, and a partially configured single endpoint (for example
`MIRASTACK_REDFISH_HOST` without `MIRASTACK_REDFISH_PASSWORD`) still raises, so a typo can
never silently downgrade a configured deployment.

## Quick Start (hardware, stdio)

```bash
export MIRASTACK_REDFISH_HOST="https://192.0.2.10"
export MIRASTACK_REDFISH_USERNAME="<bmc-username>"
export MIRASTACK_REDFISH_PASSWORD="<bmc-password>"
export MIRASTACK_REDFISH_WRITE_MODE="off"
mirastack-redfish-mcp --transport stdio
```

## Quick Start (streamable-http)

```bash
mirastack-redfish-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000 \
  --path /mcp \
  --stateless-http \
  --json-response
```

> **Warning:** binding to `0.0.0.0` exposes BMC control to every host that can reach this port. Bind to loopback unless the listener sits behind an authenticating proxy on a trusted management network.

## Configuration

### Canonical environment variables

Use `MIRASTACK_REDFISH_*` variables:

- `MIRASTACK_REDFISH_HOST`
- `MIRASTACK_REDFISH_USERNAME`
- `MIRASTACK_REDFISH_PASSWORD` or `MIRASTACK_REDFISH_PASSWORD_FILE`
- optional: `MIRASTACK_REDFISH_VERIFY_SSL` (**default: `true`**), `MIRASTACK_REDFISH_CA_BUNDLE`, `MIRASTACK_REDFISH_TIMEOUT_SEC`, `MIRASTACK_REDFISH_AUTH_MODE`

### Multi-endpoint configuration

Set `MIRASTACK_REDFISH_ENDPOINTS` to inline JSON or a YAML/JSON file:

```json
{
  "idrac-prod": {
    "base_url": "https://192.0.2.10",
    "username": "<bmc-username>",
    "password_file": "/run/secrets/idrac_password",
    "verify_ssl": true,
    "read_only": true
  },
  "ilo-lab": {
    "base_url": "https://192.0.2.11",
    "username": "<bmc-username>",
    "password": "<bmc-password>",
    "verify_ssl": true
  }
}
```

Lab-only override (not recommended for production):

```json
{
  "ilo-lab": {
    "verify_ssl": false
  }
}
```

Set `MIRASTACK_REDFISH_DEFAULT_ENDPOINT` to choose the default endpoint.

### Compatibility

Legacy bare `REDFISH_*` environment variables are still read as a fallback, with a one-time deprecation warning per variable.

### Tool registration profile

- `MIRASTACK_REDFISH_TOOL_PROFILE=full` (default): all toolsets allowed by write mode.
- `MIRASTACK_REDFISH_TOOL_PROFILE=standard`: excludes raw write escape hatches.
- `MIRASTACK_REDFISH_TOOL_PROFILE=core`: curated 15-tool small-model surface.
- `MIRASTACK_REDFISH_TOOLSETS` (comma-separated) overrides profiles with explicit toolsets.

Measured advertised tool-schema payload at `MIRASTACK_REDFISH_WRITE_MODE=full`: core 20,795 bytes (15 tools), standard 43,669 bytes (33 tools), full 54,745 bytes (40 tools). Re-measure with `python3 scripts/check_tool_metadata.py --sizes`.

## Write Safety Model

- `MIRASTACK_REDFISH_WRITE_MODE=off` (default): mutating tools are not registered.
- `MIRASTACK_REDFISH_WRITE_MODE=power`: power/reset/boot control tools are registered.
- `MIRASTACK_REDFISH_WRITE_MODE=config`: config-tier tools are registered.
- `MIRASTACK_REDFISH_WRITE_MODE=full`: full-tier tools are registered.

Every mutating tool accepts `confirm`:

- `confirm=false`: dry-run response (`dry_run=true`, `applied=false`) with `next_step`.
- `confirm=true`: action is applied.

Per-endpoint `read_only=true` overrides global write mode and blocks all writes on that endpoint.

### Tier contract

- **Power tier:** `set_power_state`, `set_boot_override`, `reset_manager`, `cancel_task`
- **Config tier:** `set_bios_attributes`, `eject_virtual_media`, `redfish_patch`, `redfish_post`, `redfish_delete`, `redfish_invoke_action`
- **Full tier:** `insert_virtual_media`, `clear_logs`, `manage_account`, `simple_update`, `reset_to_defaults`

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
make build-index
make verify
```

The schema index is generated from DMTF Redfish-Publications, pinned to one release for reproducibility. See [CONTRIBUTING.md](CONTRIBUTING.md#schema-corpus) for refresh procedure.

## Registry Publishing Notes

- `server.json` includes PyPI and OCI package definitions for MCP Registry.
- This README carries the required marker: `mcp-name: ai.mirastacklabs/mirastack-redfish-mcp`.
- Docker image includes the `io.modelcontextprotocol.server.name` OCI label.
- Install the official publisher CLI via Homebrew: `brew install mcp-publisher`.
- Do not use `npx mcp-publisher` or `pip install mcp-publisher` for registry publishing.

## Container and directory deployments

The published image puts the console script on `PATH`, so `docker run ... mirastack-redfish-mcp --transport stdio` works unchanged.

Some MCP directories ignore the repository [Dockerfile](Dockerfile) and generate their own image from source. If that generated build installs with `uv sync`, the project lands in a virtualenv at `/app/.venv` and the console script is **not** on `PATH`, so a launcher that spawns the bare name fails with `ENOENT`. Point the launcher at the absolute path instead:

```json
{
  "buildSteps": ["uv sync"],
  "cmdArguments": ["/app/.venv/bin/mirastack-redfish-mcp", "--transport", "stdio"]
}
```

A placeholder `MIRASTACK_REDFISH_ENDPOINTS` path that the platform never creates is safe - the server starts in discovery mode and serves the read-only tool surface.

## Contributing

GitHub is a public **read-only mirror**. Issues are welcome on GitHub, but pull requests opened on GitHub cannot be merged. See [CONTRIBUTING.md](CONTRIBUTING.md) for accepted contribution paths.

## Security

See [SECURITY.md](SECURITY.md).

## License

Apache-2.0.
