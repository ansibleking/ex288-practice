# Redfish MCP fleet stack

One containerized MCP server that manages your **whole fleet** of
Redfish-compatible BMCs (Dell iDRAC, HPE iLO, Lenovo XClarity, Supermicro,
OpenBMC, ...) at once, plus a portable desktop GUI/chat client to drive it.

## Why not `fredriksknese/mcp-redfish`?

That repo was the original reference point, but its LICENSE is a paid
Commercial License (EUR 100,000/licensee) — free use is capped at 30 days of
personal evaluation, with no distribution or production use permitted. This
project instead builds on **[mirastack-redfish-mcp](https://github.com/mirastacklabs-ai/mirastack-redfish-mcp)**
(Apache-2.0), which covers the same ground, natively supports multiple named
endpoints in one server process, and adds real safety design: mutating tools
aren't even registered below an explicit write-mode tier, and every mutation
is dry-run-first. See `server/README.md` for its full docs.

## Layout

- `server/` — unmodified clone of mirastack-redfish-mcp. Ships its own
  `Dockerfile`; built here via `docker compose`.
- `endpoints.example.json` — template for your fleet: one entry per BMC
  (name, base_url, username, password/password_file, verify_ssl, read_only).
  Copy to `endpoints.json` (gitignored) and fill in your real servers.
- `docker-compose.yml` — builds the server image, mounts `endpoints.json`,
  and runs it with the `streamable-http` MCP transport on
  `127.0.0.1:8787/mcp`. An optional `mockup` profile brings up **two** fake
  BMCs (`endpoints.mockup.json`) so you can try fleet behavior with zero real
  hardware.
- `client/` — Electron + React desktop app. Every tool call — and every
  chat turn — targets a specific server by name; a picker in the top bar
  lets you switch which one is "active" fleet-wide:
  - **Dashboard** tab: a generic MCP tool browser — pick any of the 25
    registered tools, fill in a form generated from its JSON schema (the
    `endpoint` field defaults to whichever server is selected in the
    picker), run it, see the raw result. No LLM involved.
  - **Chat** tab: natural-language requests, answered by Claude deciding
    which MCP tools to call. Ask about "all servers" and it calls the
    relevant tool once per configured endpoint and summarizes across them
    (needs an Anthropic API key, set in Settings).

## 1. Run the server

```bash
cp .env.example .env
cp endpoints.example.json endpoints.json   # then edit in your real BMCs
docker compose up -d --build
```

Or try it against two fake BMCs first (no real hardware needed):

```bash
cp .env.example .env
cp endpoints.mockup.json endpoints.json
docker compose --profile mockup up -d --build
```

**Verified end-to-end** during setup: built the image, brought up two mockup
BMCs, and confirmed `list_endpoints` reports both, while `list_systems` with
`endpoint: "mockup-a"` / `"mockup-b"` correctly routes to each one
independently through the same MCP server/session.

**Start with `MIRASTACK_REDFISH_WRITE_MODE=off`** (the default in
`.env.example`) until you're comfortable — this means power/boot/firmware/
account mutation tools aren't even registered, fleet-wide. The port is
published on `127.0.0.1` only; there's no auth in front of the MCP endpoint
itself, so don't widen that binding without an authenticating proxy in front,
on a trusted management network.

**Gotcha:** `endpoints.json` must exist *before* `docker compose up` — Docker
bind-mounts a missing file as an empty *directory*, which the server treats
as a hard startup failure (`IsADirectoryError`) rather than degrading
gracefully. Always `cp endpoints.example.json endpoints.json` (or the mockup
variant) first.

If you've already hit this once, that phantom directory is still sitting
there — running `cp endpoints.example.json endpoints.json` again will *not*
fix it, since `cp` copies a file **into** an existing directory instead of
replacing it, so the container keeps crash-looping. Check with `ls -la
endpoints.json`; if it prints a directory listing instead of a JSON file,
remove it first:

```bash
docker compose rm -f redfish-mcp   # drop the crash-looping container
rm -rf endpoints.json              # it's a directory, not the file you wanted
cp endpoints.example.json endpoints.json
docker compose up -d --build redfish-mcp
```

## 2. Run the GUI client

No Node.js is required on the host beyond what's needed to build the app once
(this dev machine has none installed either — verified via a `node:20`
container instead, see below).

```bash
cd client
npm install
npm run dev        # Electron window opens, hot-reloads
```

On first launch, open **Settings** and set:
- **MCP server URL**: `http://127.0.0.1:8787/mcp` (matches the compose port)
- **Anthropic API key**: only needed for the Chat tab

Once connected, the top bar shows a **Server** dropdown listing every
endpoint from `endpoints.json` — switch it to change which BMC the Dashboard
and Chat tabs target by default.

### Building a portable binary

```bash
cd client
npm run dist
```

Produces a Linux AppImage / Windows portable .exe / macOS .dmg in
`client/release/` via `electron-builder`, per the platform you build on.

## What's been verified

- `server/`: Docker image builds; container runs `--transport streamable-http`
  against a **two-endpoint fleet** config, correctly serving
  `initialize`/`tools/list`/`list_endpoints`, and routing `tools/call` for
  `list_systems` to the right backend BMC per the `endpoint` argument — all
  confirmed via `docker compose --profile mockup`.
- `client/`: full TypeScript typecheck, Vite renderer build, and Electron
  main/preload bundling all succeed (`npm run build`, run inside a `node:20`
  container since Node isn't installed on this host). **Not yet verified**:
  actually launching the Electron window (no display in this environment) or
  a live Chat-tab run against the real Anthropic API — walk through both by
  hand after `npm run dev`.
