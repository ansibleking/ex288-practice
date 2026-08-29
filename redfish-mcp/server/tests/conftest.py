from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from mirastack_redfish_mcp.schema.index import SchemaIndex
from mirastack_redfish_mcp.schema.resolver import UriResolver

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.redfish_corpus import CorpusError, ensure_corpus  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def references_root() -> Path:
    """DMTF corpus checkout, cloned from GitHub at the pinned ref when not already cached.

    Set REDFISH_REQUIRE_CORPUS=1 (CI does) to turn an unavailable corpus into a failure rather
    than a skip, so corpus-backed coverage cannot silently disappear from a pipeline.
    """
    try:
        corpus, _ = ensure_corpus()
    except CorpusError as exc:
        if os.getenv("REDFISH_REQUIRE_CORPUS") == "1":
            pytest.fail(f"Redfish corpus is required but unavailable: {exc}")
        pytest.skip(f"Redfish corpus unavailable: {exc}")
    return corpus


@pytest.fixture(scope="session")
def schema_index(repo_root: Path) -> SchemaIndex:
    return SchemaIndex.from_path(
        repo_root / "src" / "mirastack_redfish_mcp" / "data" / "redfish_index.json.gz"
    )


@pytest.fixture(scope="session")
def uri_resolver(schema_index: SchemaIndex) -> UriResolver:
    return UriResolver(schema_index)
