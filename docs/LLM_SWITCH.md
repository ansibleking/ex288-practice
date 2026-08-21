# How to switch LLM

The agent always uses a **profile** from `llm-profiles.json`.  
If you don't pick one, it uses `"default"` (currently `qwen-122b`).

`.env` values like `ONPREM_LLM_BASE_URL` are **only used when no profile is selected**.  
They no longer override `--llm claude-sonnet`.

## 1. List profiles

```bash
sudo docker-compose --profile agent run --rm agent -- --list-llm-profiles
```

## 2. Show which LLM will be used

```bash
LLM_PROFILE=claude-sonnet sudo docker-compose --profile agent run --rm agent -- --show-llm
```

## 3. Switch LLM per command

### On-prem Qwen (default)

```bash
sudo docker-compose --profile agent run --rm agent -- --llm qwen-122b "Get employee wise attendance report"
```



### Anthropic Claude

```bash
# ANTHROPIC_API_KEY must be in .env
sudo docker-compose --profile agent run net "Get employee wise attendance report"
sudo docker-compose --profile agent run --rm agent -- --llm claude-haiku "Quick summary"
```



### Using env var instead of --llm (easiest in Docker)

```bash
LLM_PROFILE=claude-sonnet sudo docker-compose --profile agent run --rm agent -- "Get employee wise attendance report"
LLM_PROFILE=qwen-122b sudo docker-compose --profile agent run --rm agent -- "Get employee wise attendance report"
```



## 4. Setup files

```bash
cp llm-profiles.example.json llm-profiles.json
```

Edit `llm-profiles.json` — set `"default"` to the profile you use most.

`.env` needs:

```bash
# For qwen / on-prem profiles
OPENAI_API_KEY=your-jwt-or-key

# For claude profiles
ANTHROPIC_API_KEY=sk-ant-...
```



## 5. Rebuild after code changes

```bash
sudo docker-compose build --no-cache
```



## Quick reference


| Want             | Command                                                                                      |
| ---------------- | -------------------------------------------------------------------------------------------- |
| Qwen on-prem     | `LLM_PROFILE=qwen-122b sudo docker-compose --profile agent run --rm agent -- "question"`     |
| Claude           | `LLM_PROFILE=claude-sonnet sudo docker-compose --profile agent run --rm agent -- "question"` |
| Check active LLM | `... agent -- --show-llm`                                                                    |
| List profiles    | `... agent -- --list-llm-profiles`                                                           |


**Always put** `--` **before agent flags**, and the question in quotes at the end.