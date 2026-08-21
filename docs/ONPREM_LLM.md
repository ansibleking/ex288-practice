# On-prem LLM setup

The agent uses an **OpenAI-compatible** chat API. Most on-prem stacks (Ollama, vLLM, LocalAI, LiteLLM, OpenWebUI) expose this format.

## Configure `.env`

```bash
AGENT_LLM_PROVIDER=openai
ONPREM_LLM_BASE_URL=https://your-llm-host.example.com/v1
ONPREM_LLM_MODEL=qwen/qwen3.5-122b-a10b
OPENAI_API_KEY=your-jwt-or-api-key
LLM_TIMEOUT=120
```

| Variable | Notes |
|----------|-------|
| `ONPREM_LLM_BASE_URL` | OpenAI-compatible `/v1` endpoint (preferred) |
| `ONPREM_LLM_MODEL` | Model id your server expects |
| `OPENAI_API_KEY` | JWT or API key for the serving platform |
| `ONPREM_LLM_VERIFY_SSL` | Set `false` if internal HTTPS uses a private CA (dev only) |
| `LLM_CA_BUNDLE` | Path to corporate root CA `.pem` (preferred over disabling verify) |
| `OPENAI_BASE_URL` | Alias for `ONPREM_LLM_BASE_URL` |
| `AGENT_MODEL` | Alias for `ONPREM_LLM_MODEL` |

## Examples

### Ollama on the same host

```bash
OPENAI_BASE_URL=http://host.containers.internal:11434/v1
OPENAI_API_KEY=ollama
AGENT_MODEL=llama3.1
```

From the host (no container):

```bash
OPENAI_BASE_URL=http://127.0.0.1:11434/v1
```

### vLLM

```bash
OPENAI_BASE_URL=http://llm-server.emaratech.ae:8000/v1
OPENAI_API_KEY=local
AGENT_MODEL=meta-llama/Llama-3.1-8B-Instruct
```

## Run in container

```bash
podman-compose build
podman-compose --profile agent run --rm agent "Show my attendance for last week"
```

If the LLM runs on the host, `docker-compose.yml` already maps:

```yaml
extra_hosts:
  - "host.containers.internal:host-gateway"
```

If that fails on Podman, use the host IP directly or uncomment `network_mode: host` on the `agent` service.

## Tool calling requirement

The agent needs a model that supports **function/tool calling**. Not all on-prem models do.

If the LLM returns text but never calls MCP tools, switch to a model/server build with tool-use support (e.g. Llama 3.1+ via Ollama, or vLLM with a tool-capable instruct model).

## Troubleshooting

| Error | Fix |
|-------|-----|
| `401 Incorrect API key` | Remove invalid cloud `OPENAI_API_KEY`; set `OPENAI_BASE_URL` for on-prem |
| Connection refused to LLM | Use host IP / `host.containers.internal` / `network_mode: host` |
| `CERTIFICATE_VERIFY_FAILED` | Set `ONPREM_LLM_VERIFY_SSL=false` or mount CA via `LLM_CA_BUNDLE=/certs/ca.pem` |
| Model answers without data | Model may not support tools; change model or server |
| TAMS API errors | Check `TAMS_USERNAME`, `TAMS_PASSWORD`, VPN |
