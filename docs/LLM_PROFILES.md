# Switch LLM on demand

## 1. Named profiles (recommended)

Copy and edit profiles:

```bash
cp llm-profiles.example.json llm-profiles.json
```

Run with a profile:

```bash
tams-agent --llm qwen-122b "Show my attendance for last week"
tams-agent --llm qwen-fast "Summarize late arrivals"
tams-agent --list-llm-profiles
tams-agent --show-llm
```

One-off env switch (no flags):

```bash
LLM_PROFILE=qwen-fast tams-agent "Show my attendance"
```

## 2. CLI overrides (single run)

Override model or URL without editing files:

```bash
tams-agent --model qwen/qwen3.5-32b --llm-url https://other-host.example.com/v1 "question"
tams-agent --llm qwen-122b --model qwen/qwen3.5-122b-a10b "question"
tams-agent --llm-key "$OPENAI_API_KEY" --llm-verify-ssl false "question"
```

## 3. Priority order

1. CLI flags (`--model`, `--llm-url`, `--llm-key`, …)
2. `--llm PROFILE` or `LLM_PROFILE`
3. `default` entry in `llm-profiles.json`
4. `.env` values (`ONPREM_LLM_*`, `OPENAI_API_KEY`)

When you pass `--llm PROFILE`, that profile’s `base_url` and `model` take effect. Shared secrets such as `OPENAI_API_KEY` still come from `.env` unless the profile or CLI sets them.

## 4. Docker

Mount your profiles file:

```yaml
volumes:
  - ./llm-profiles.json:/app/llm-profiles.json:ro
```

Run:

```bash
podman-compose build
LLM_PROFILE=qwen-122b podman-compose --profile agent run --rm agent "Show my attendance"
./scripts/docker-agent.sh --llm qwen-122b "Get employee wise attendance report"
```

## Anthropic

```bash
tams-agent --llm claude-sonnet "Show my attendance"
tams-agent --llm claude-haiku "Quick summary of absences"
tams-agent --llm-provider anthropic --model claude-sonnet-4-20250514 "question"
```

Add to `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
# optional proxy:
# ANTHROPIC_BASE_URL=https://your-anthropic-proxy.example.com
```

Profile example:

```json
"claude-sonnet": {
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514"
}
```

The API key is read from `ANTHROPIC_API_KEY` in `.env` unless the profile or `--llm-key` sets it.

## Example `llm-profiles.json`

```json
{
  "default": "qwen-122b",
  "profiles": {
    "qwen-122b": {
      "base_url": "https://your-qwen-endpoint/v1",
      "model": "qwen/qwen3.5-122b-a10b",
      "verify_ssl": false
    },
    "qwen-fast": {
      "base_url": "https://your-fast-endpoint/v1",
      "model": "qwen/qwen3.5-32b",
      "verify_ssl": false
    }
  }
}
```
