from __future__ import annotations

import socket
from urllib.parse import urlparse

from tams_agent.llm import describe_llm_target, get_active_config
from tams_agent.ssl_util import make_sync_http_client


def _dns_check(hostname: str) -> str:
    try:
        ip = socket.gethostbyname(hostname)
        return f"DNS OK: {hostname} -> {ip}"
    except socket.gaierror as exc:
        return f"DNS FAILED: {hostname} ({exc})"


def _tcp_check(hostname: str, port: int, timeout: float = 5.0) -> str:
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return f"TCP OK: {hostname}:{port}"
    except OSError as exc:
        return f"TCP FAILED: {hostname}:{port} ({exc})"


def check_llm_connectivity() -> int:
    cfg = get_active_config()
    print(describe_llm_target())

    if not cfg.base_url:
        print("No base_url configured — skipping HTTP check (cloud provider).")
        return 0

    parsed = urlparse(cfg.base_url)
    if not parsed.hostname:
        print(f"Invalid base URL: {cfg.base_url}")
        return 1

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    print(_dns_check(parsed.hostname))
    print(_tcp_check(parsed.hostname, port))

    models_url = f"{cfg.base_url.rstrip('/')}/models"
    print(f"HTTP GET {models_url}")
    try:
        with make_sync_http_client(timeout=min(cfg.timeout, 30.0), verify=cfg.verify_ssl) as client:
            response = client.get(
                models_url,
                headers={"Authorization": f"Bearer {cfg.api_key}"},
            )
            print(f"HTTP OK: status={response.status_code}")
            return 0 if response.status_code < 500 else 1
    except Exception as exc:
        print(f"HTTP FAILED: {exc}")
        print()
        print("If this works on the host but fails in Docker:")
        print("  1. Uncomment network_mode: host in docker-compose.yml (agent service)")
        print("  2. Or run on host: tams-agent \"your question\" (without Docker)")
        print("  3. Re-test: docker compose --profile agent run --rm agent -- --check-llm")
        return 1
