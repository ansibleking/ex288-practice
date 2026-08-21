FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SWAGGER_SPEC_PATH=/app/swagger.json

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY swagger.json /app/swagger.json
COPY llm-profiles.example.json /app/llm-profiles.json
COPY mcp-server/ /app/mcp-server/
COPY agent/ /app/agent/

RUN pip install /app/mcp-server /app/agent

# Default service: MCP server over stdio (for Cursor / MCP clients)
ENTRYPOINT ["tams-mcp"]
