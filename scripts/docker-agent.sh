#!/usr/bin/env bash
# Run the TAMS agent in Docker/Podman Compose without flag-passing issues.
#
# Usage:
#   ./scripts/docker-agent.sh "Show my attendance for last week"
#   ./scripts/docker-agent.sh --llm qwen-122b "Get employee wise attendance report"
#   LLM_PROFILE=claude-sonnet ./scripts/docker-agent.sh "Summarize absences"
#   ./scripts/docker-agent.sh --list-tools
#   ./scripts/docker-agent.sh -h

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker-compose)
if ! command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker compose)
fi

exec "${COMPOSE[@]}" --profile agent run --rm agent -- "$@"
