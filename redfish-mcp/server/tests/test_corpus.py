from __future__ import annotations

import gzip
import json
import subprocess
from pathlib import Path

import pytest

from tools.redfish_corpus import (
    CORPUS_REF,
    CORPUS_URL,
    CorpusError,
    _release_sort_key,
    default_cache_dir,
    ensure_corpus,
    verify_corpus,
)


def _make_corpus_checkout(root: Path, tag: str) -> Path:
    """A minimal git checkout shaped like Redfish-Publications, built offline."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "json-schema").mkdir()
    (root / "registries").mkdir()
    (root / "json-schema" / "Example.json").write_text("{}", encoding="utf-8")
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    for args in (
        ["init", "--quiet", "-b", "main"],
        ["add", "-A"],
        ["commit", "--quiet", "-m", "corpus"],
        ["tag", tag],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, env=env, capture_output=True)
    return root


def test_verify_corpus_accepts_matching_ref(tmp_path: Path) -> None:
    corpus = _make_corpus_checkout(tmp_path / "corpus", "2026.1")
    commit = verify_corpus(corpus, "2026.1")
    assert len(commit) == 40


def test_verify_corpus_rejects_unknown_ref(tmp_path: Path) -> None:
    corpus = _make_corpus_checkout(tmp_path / "corpus", "2026.1")
    with pytest.raises(CorpusError, match="does not know ref"):
        verify_corpus(corpus, "2099.9")


def test_verify_corpus_rejects_wrong_commit(tmp_path: Path) -> None:
    """A checkout sitting on a different commit than the pinned tag must not build the index."""
    corpus = _make_corpus_checkout(tmp_path / "corpus", "2026.1")
    (corpus / "json-schema" / "Extra.json").write_text("{}", encoding="utf-8")
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    subprocess.run(["git", "add", "-A"], cwd=corpus, check=True, env=env, capture_output=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "drift"],
        cwd=corpus,
        check=True,
        env=env,
        capture_output=True,
    )
    with pytest.raises(CorpusError, match="is checked out at"):
        verify_corpus(corpus, "2026.1")


def test_verify_corpus_rejects_non_git_directory(tmp_path: Path) -> None:
    corpus = tmp_path / "plain"
    (corpus / "json-schema").mkdir(parents=True)
    (corpus / "registries").mkdir()
    with pytest.raises(CorpusError, match="not a git checkout"):
        verify_corpus(corpus, "2026.1")


def test_verify_corpus_rejects_missing_directories(tmp_path: Path) -> None:
    corpus = tmp_path / "empty"
    corpus.mkdir()
    with pytest.raises(CorpusError, match="missing required directories"):
        verify_corpus(corpus, "2026.1")


def test_ensure_corpus_offline_without_cache_fails(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="offline"):
        ensure_corpus(ref="2026.1", cache_dir=tmp_path / "cache", offline=True)


def test_ensure_corpus_reuses_cached_checkout(tmp_path: Path) -> None:
    """A populated cache entry is reused without any network access."""
    cache = tmp_path / "cache"
    _make_corpus_checkout(cache / "2026.1", "2026.1")
    path, commit = ensure_corpus(ref="2026.1", cache_dir=cache, offline=True)
    assert path == cache / "2026.1"
    assert len(commit) == 40


def test_ensure_corpus_missing_local_path_fails(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="corpus path not found"):
        ensure_corpus(local=tmp_path / "nope")


def test_cache_dir_honours_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDFISH_CORPUS_CACHE", str(tmp_path / "custom"))
    assert default_cache_dir() == tmp_path / "custom"


def test_release_tags_sort_numerically() -> None:
    tags = ["2024.4", "2025.10", "2025.2", "2026.1"]
    assert max(tags, key=_release_sort_key) == "2026.1"
    assert sorted(tags, key=_release_sort_key)[-2] == "2025.10"


def test_committed_index_matches_pinned_corpus_ref(repo_root: Path) -> None:
    """The shipped artifact must record the ref the builder is pinned to."""
    index_path = repo_root / "src" / "mirastack_redfish_mcp" / "data" / "redfish_index.json.gz"
    with gzip.open(index_path) as handle:
        source = json.loads(handle.read())["source"]
    assert source["corpus_ref"] == CORPUS_REF, (
        "CORPUS_REF was bumped without rebuilding the index; run `make build-index`"
    )
    assert source["corpus_url"] == CORPUS_URL
    assert len(source["corpus_commit"]) == 40
