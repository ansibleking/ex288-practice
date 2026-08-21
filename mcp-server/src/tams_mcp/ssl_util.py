from __future__ import annotations

import os
from pathlib import Path


def _env_flag(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip().lower() not in {"0", "false", "no", "off"}


def ssl_verify_setting() -> bool | str:
    for key in ("TAMS_VERIFY_SSL", "HTTP_VERIFY_SSL", "ONPREM_LLM_VERIFY_SSL", "LLM_VERIFY_SSL"):
        flag = _env_flag(key)
        if flag is not None:
            return flag

    for key in ("TAMS_CA_BUNDLE", "LLM_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        path = os.getenv(key)
        if path and Path(path).is_file():
            return path

    return True
