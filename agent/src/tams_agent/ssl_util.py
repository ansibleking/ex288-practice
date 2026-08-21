from __future__ import annotations

import os
from pathlib import Path


def _env_flag(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip().lower() not in {"0", "false", "no", "off"}


def ssl_verify_setting() -> bool | str:
    """Return False, True, or a path to a CA bundle for httpx verify=."""
    for key in ("ONPREM_LLM_VERIFY_SSL", "LLM_VERIFY_SSL", "TAMS_VERIFY_SSL", "HTTP_VERIFY_SSL"):
        flag = _env_flag(key)
        if flag is not None:
            return flag

    for key in ("LLM_CA_BUNDLE", "TAMS_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        path = os.getenv(key)
        if path and Path(path).is_file():
            return path

    return True


def _client_kwargs(timeout: float | None, verify: bool | str | None) -> dict:
    if verify is None:
        verify = ssl_verify_setting()
    kwargs: dict = {"verify": verify}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return kwargs


def make_sync_http_client(timeout: float | None = None, verify: bool | str | None = None):
    kwargs = _client_kwargs(timeout, verify)
    try:
        import httpx2

        return httpx2.Client(**kwargs)
    except ImportError:
        import httpx

        return httpx.Client(**kwargs)


def make_async_http_client(timeout: float | None = None, verify: bool | str | None = None):
    kwargs = _client_kwargs(timeout, verify if verify is not None else ssl_verify_setting())
    try:
        import httpx2

        return httpx2.AsyncClient(**kwargs)
    except ImportError:
        import httpx

        return httpx.AsyncClient(**kwargs)
