from __future__ import annotations

import json
from pathlib import Path

import pytest

from mirastack_redfish_mcp.schema.resolver import UriResolver


def _should_ignore_uri(uri: str) -> bool:
    return uri.endswith("/odata") or uri.endswith("/$metadata")


@pytest.mark.slow
def test_mockup_odata_ids_resolve(uri_resolver: UriResolver, references_root: Path) -> None:
    mockups_root = references_root / "mockups"
    unresolved: list[tuple[Path, str]] = []
    checked = 0

    for path in mockups_root.rglob("index.json"):
        if path.name != "index.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        uri = payload.get("@odata.id")
        if not isinstance(uri, str) or _should_ignore_uri(uri):
            continue
        checked += 1
        if uri_resolver.resolve(uri) is None:
            unresolved.append((path, uri))

    assert checked > 500
    assert not unresolved, f"unresolved @odata.id values: {unresolved[:20]}"


@pytest.mark.slow
def test_dsp2046_examples_parse(references_root: Path) -> None:
    examples_root = references_root / "mockups" / "DSP2046-examples"
    count = 0
    for path in examples_root.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        count += 1
    assert count >= 250
