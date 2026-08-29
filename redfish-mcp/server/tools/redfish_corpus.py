#!/usr/bin/env python3
"""Provision the DMTF Redfish-Publications corpus that the schema index is built from."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CORPUS_URL = "https://github.com/DMTF/Redfish-Publications.git"

# Pinned DMTF publication tag. The schema index shipped in src/mirastack_redfish_mcp/data is built from
# exactly this ref, which is what makes `make build-index` reproducible and lets CI compare the
# rebuilt artifact byte for byte. Bump it deliberately: see "Refreshing the corpus" in
# CONTRIBUTING.md. `tools/redfish_corpus.py --check-latest` reports when DMTF publishes a newer
# release.
CORPUS_REF = "2026.1"

REQUIRED_SUBDIRS = ("json-schema", "registries")
RELEASE_TAG_RE = re.compile(r"^(\d+)\.(\d+)$")


class CorpusError(RuntimeError):
    """Raised when the corpus cannot be provisioned or cannot be verified."""


def default_cache_dir() -> Path:
    """Directory that holds one checkout per corpus ref."""
    override = os.getenv("REDFISH_CORPUS_CACHE")
    if override:
        return Path(override).expanduser()
    xdg = os.getenv("XDG_CACHE_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return root / "mirastack-redfish-mcp" / "corpus"


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd is not None else None,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - depends on host tooling
        raise CorpusError(
            "git executable not found; install git or pass --corpus with a local checkout"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise CorpusError(f"git {' '.join(args)} failed: {exc.stderr.strip()}") from exc
    return completed.stdout.strip()


def _has_corpus_payload(path: Path) -> bool:
    return all((path / name).is_dir() for name in REQUIRED_SUBDIRS)


def verify_corpus(path: Path, ref: str) -> str:
    """Return the resolved commit, or raise when the checkout is not usable at `ref`."""
    if not _has_corpus_payload(path):
        missing = [name for name in REQUIRED_SUBDIRS if not (path / name).is_dir()]
        raise CorpusError(f"corpus at {path} is missing required directories: {missing}")
    if not (path / ".git").exists():
        raise CorpusError(
            f"corpus at {path} is not a git checkout, so its DMTF release cannot be verified; "
            "omit --corpus to fetch the pinned ref from GitHub instead"
        )
    head = _git("rev-parse", "HEAD", cwd=path)
    try:
        wanted = _git("rev-parse", f"{ref}^{{commit}}", cwd=path)
    except CorpusError as exc:
        raise CorpusError(
            f"corpus at {path} does not know ref {ref!r} (fetch tags, or omit --corpus)"
        ) from exc
    if head != wanted:
        raise CorpusError(
            f"corpus at {path} is checked out at {head[:12]} but ref {ref!r} is {wanted[:12]}; "
            "check out the pinned ref or pass --corpus-ref to build from a different release"
        )
    return head


def ensure_corpus(
    *,
    ref: str = CORPUS_REF,
    local: Path | None = None,
    cache_dir: Path | None = None,
    offline: bool = False,
) -> tuple[Path, str]:
    """Return (corpus_path, commit), cloning the pinned ref from GitHub when needed."""
    if local is not None:
        path = Path(local).expanduser()
        if not path.is_dir():
            raise CorpusError(f"corpus path not found: {path}")
        return path, verify_corpus(path, ref)

    target = (cache_dir or default_cache_dir()).expanduser() / ref
    if target.is_dir():
        try:
            return target, verify_corpus(target, ref)
        except CorpusError:
            if offline:
                raise
            # A partial or superseded checkout is safe to discard; it is a cache entry.
            shutil.rmtree(target)
    if offline:
        raise CorpusError(f"corpus ref {ref!r} is not cached at {target} and offline was requested")

    target.parent.mkdir(parents=True, exist_ok=True)
    _git("clone", "--quiet", "--depth", "1", "--branch", ref, CORPUS_URL, str(target))
    return target, verify_corpus(target, ref)


def _release_sort_key(tag: str) -> tuple[int, int]:
    match = RELEASE_TAG_RE.match(tag)
    if match is None:  # pragma: no cover - filtered before use
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def latest_release_ref() -> str:
    """Newest `YYYY.N` release tag published by DMTF."""
    output = _git("ls-remote", "--tags", "--refs", CORPUS_URL)
    tags = [
        line.rsplit("refs/tags/", 1)[-1]
        for line in output.splitlines()
        if "refs/tags/" in line
    ]
    releases = [tag for tag in tags if RELEASE_TAG_RE.match(tag)]
    if not releases:
        raise CorpusError(f"no release tags found at {CORPUS_URL}")
    return max(releases, key=_release_sort_key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-latest",
        action="store_true",
        help="Compare the pinned ref against the newest DMTF release and exit 1 when behind",
    )
    parser.add_argument("--ref", default=CORPUS_REF, help="Corpus ref to provision")
    parser.add_argument("--print-path", action="store_true", help="Provision and print the path")
    args = parser.parse_args()

    try:
        if args.check_latest:
            latest = latest_release_ref()
            print(f"pinned: {CORPUS_REF}")
            print(f"latest: {latest}")
            if _release_sort_key(latest) > _release_sort_key(CORPUS_REF):
                print(
                    f"DMTF published {latest}. Refresh with: "
                    f"make refresh-corpus CORPUS_REF={latest}"
                )
                return 1
            print("Pinned corpus is current.")
            return 0

        path, commit = ensure_corpus(ref=args.ref)
        if args.print_path:
            print(path)
        else:
            print(f"corpus ref {args.ref} at {commit} -> {path}")
        return 0
    except CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
