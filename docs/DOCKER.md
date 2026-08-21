# Docker

Run the TAMS MCP server and agent in containers.

## Build

```bash
cd /home/mayil/attedance
cp .env.example .env   # fill in TAMS credentials
docker compose build
```

## MCP server (stdio)

List tools:

```bash
docker compose run --rm mcp --list-tools
```

Cursor MCP config (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "tams-attendance": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "--env-file",
        "/home/mayil/attedance/.env",
        "tams-attendance:latest"
      ]
    }
  }
}
```

## Agent CLI

**Rebuild after code changes** (required for `--llm` and other new flags):

```bash
sudo docker-compose build --no-cache
```

The container entrypoint is already `tams-agent`. Do **not** pass `tams-agent` again.

### Recommended: use the helper script

```bash
chmod +x scripts/docker-agent.sh
./scripts/docker-agent.sh --llm qwen-122b "Get employee wise attendance report"
./scripts/docker-agent.sh "Show my attendance for last week"
./scripts/docker-agent.sh --list-tools
```

### Show help (no LLM call)

```bash
sudo docker-compose --profile agent run --rm --entrypoint tams-agent agent -h
# or after rebuild with argv fix:
sudo docker-compose --profile agent run --rm agent -- -h
```

### Diagnose LLM network (before running queries)

```bash
LLM_PROFILE=qwen-122b sudo docker-compose --profile agent run --rm agent -- --check-llm
```

### Run a query

```bash
LLM_PROFILE=qwen-122b sudo docker-compose --profile agent run --rm agent -- "Get employee wise attendance report"
```

Wrong:

```bash
# BAD — old image or flags not passed correctly
sudo docker-compose --profile agent run --rm agent --llm qwen-122b "question"
sudo docker-compose --profile agent run --rm agent tams-agent "question"
```

## VPN / internal DNS

Corporate endpoints (`*.dnrd.gov.ae`, `*.emaratech.ae`) are usually only reachable via **host VPN/DNS**. The `agent` service uses **`network_mode: host`** so it shares the host network stack.

Test connectivity:

```bash
# on host
curl -k "$ONPREM_LLM_BASE_URL/models" -H "Authorization: Bearer $OPENAI_API_KEY"

# in container
sudo docker-compose --profile agent run --rm agent -- --check-llm
LLM_PROFILE=qwen-122b sudo docker-compose --profile agent run --rm agent -- --check-llm
```

If host works but container fails, confirm `network_mode: host` is set under `agent` in `docker-compose.yml` and rebuild.

## Environment

All settings come from `.env` via `env_file`. Required for API calls:

- `TAMS_USERNAME`, `TAMS_PASSWORD`
- `TAMS_PAYCODE`, `TAMS_COMPANY_CODE`
- `TAMS_AUTH_COMP`, `TAMS_AUTH_DEPT`, `TAMS_AUTH_LOC`, `TAMS_AUTH_SITE`

For the agent profile, configure your LLM — see [docs/ONPREM_LLM.md](ONPREM_LLM.md).

On-prem example in `.env`:

```bash
OPENAI_BASE_URL=http://host.containers.internal:11434/v1
OPENAI_API_KEY=local
AGENT_MODEL=llama3.1
```

## Image contents

| Path | Purpose |
|------|---------|
| `/app/swagger.json` | Connect_API spec |
| `tams-mcp` | MCP server entrypoint |
| `tams-agent` | LLM agent entrypoint |

Swagger path defaults to `/app/swagger.json` inside the container.
