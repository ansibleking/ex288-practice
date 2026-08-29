FROM python:3.12-slim

LABEL org.opencontainers.image.title="mirastack-redfish-mcp"
LABEL org.opencontainers.image.description="Schema-aware MCP server for Redfish APIs"
LABEL org.opencontainers.image.source="https://github.com/mirastacklabs-ai/mirastack-redfish-mcp"
LABEL io.modelcontextprotocol.server.name="ai.mirastacklabs/mirastack-redfish-mcp"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE SECURITY.md CONTRIBUTING.md server.json /app/
COPY src /app/src

RUN pip install --no-cache-dir .

ENTRYPOINT ["mirastack-redfish-mcp"]
CMD ["--transport", "stdio"]

