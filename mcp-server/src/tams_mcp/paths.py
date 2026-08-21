from __future__ import annotations

from pathlib import Path


def resolve_swagger_path(spec_path: str) -> Path:
    path = Path(spec_path)
    if path.is_absolute() and path.exists():
        return path

    candidates = [
        Path.cwd() / path,
        Path("/app") / path,
        Path(__file__).resolve().parents[3] / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return Path.cwd() / path
