# Security Policy

## Scope

This MCP server executes operational actions on Redfish-enabled infrastructure. Security controls focus on:

- credential handling
- transport security (TLS and certificate validation)
- write-operation safety
- endpoint isolation

## Supported Versions

Only the latest released `0.1.x` version is supported for security fixes at this stage.

## Reporting a Vulnerability

Email `security@mirastacklabs.ai`.

Response SLA:

- Initial acknowledgment within 1 business day.
- Triage decision within 3 business days.
- Ongoing status updates at least weekly until resolution or accepted risk.

When reporting:

- include exact version and commit
- include endpoint type (for example iDRAC, iLO, XCC, OpenBMC)
- include minimal reproduction steps
- include sanitized logs and request metadata

Do not include real credentials, session tokens, or private network details in public issues.

## Security Controls Implemented

- `MIRASTACK_REDFISH_PASSWORD_FILE` support for secret mounts (avoids plain env value in process list snapshots).
- Session token handling through `X-Auth-Token`; sessions are torn down on shutdown when possible.
- Optional strict TLS verification with custom CA bundle (`MIRASTACK_REDFISH_CA_BUNDLE`).
- Cross-host URI protection: the client rejects absolute URIs that target a different host.
- Write tools are disabled by default and require explicit write-mode opt-in.
- Mutating tools support dry-run preview and confirmation gating.
- Per-endpoint `read_only` mode hard-blocks writes.

## Operational Recommendations

- Keep `MIRASTACK_REDFISH_VERIFY_SSL=true` in production.
- Use dedicated least-privilege service accounts for each endpoint.
- Separate production and lab endpoints with distinct server instances.
- Start with `MIRASTACK_REDFISH_WRITE_MODE=off`; only raise tiers after validation.
- Restrict network egress so the server reaches only intended BMC subnets.
- Rotate credentials regularly and revoke stale Redfish sessions.

