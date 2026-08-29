#!/usr/bin/env python3
"""Ensure project version is aligned across packaging metadata."""

from __future__ import annotations

import json
import re
from pathlib import Path


def _read_pyproject_version(pyproject_path: Path) -> str:
    text = pyproject_path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if not match:
        raise SystemExit("unable to find project version in pyproject.toml")
    return match.group(1)


def _read_init_version(init_path: Path) -> str:
    text = init_path.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if not match:
        raise SystemExit("unable to find __version__ in src/mirastack_redfish_mcp/__init__.py")
    return match.group(1)


def _read_server_json_versions(server_json_path: Path) -> dict[str, str]:
    """Collect every version-bearing field in server.json, keyed by where it came from."""
    payload = json.loads(server_json_path.read_text(encoding="utf-8"))
    top_level = payload.get("version")
    if not isinstance(top_level, str):
        raise SystemExit("server.json missing top-level version")
    versions = {"server.json:version": top_level}
    packages = payload.get("packages")
    if not isinstance(packages, list):
        raise SystemExit("server.json missing packages array")
    for package in packages:
        registry = package.get("registryType")
        if registry == "pypi":
            package_version = package.get("version")
            if not isinstance(package_version, str):
                raise SystemExit("server.json pypi package missing version")
            versions["server.json:packages[pypi].version"] = package_version
        elif registry == "oci":
            identifier = package.get("identifier")
            if not isinstance(identifier, str) or ":" not in identifier:
                raise SystemExit("server.json oci package identifier must be image:tag")
            versions["server.json:packages[oci].identifier"] = identifier.rsplit(":", 1)[1]
    return versions


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    expected = _read_pyproject_version(repo / "pyproject.toml")
    found = {"pyproject.toml:version": expected}
    found["src/mirastack_redfish_mcp/__init__.py:__version__"] = _read_init_version(
        repo / "src" / "mirastack_redfish_mcp" / "__init__.py"
    )
    found.update(_read_server_json_versions(repo / "server.json"))

    mismatches = [f"{source}={value}" for source, value in found.items() if value != expected]
    if mismatches:
        raise SystemExit(
            f"version mismatch: expected {expected} from pyproject.toml, found "
            + ", ".join(mismatches)
        )
    print(f"Versions aligned across {len(found)} sources: {expected}")


if __name__ == "__main__":
    main()
