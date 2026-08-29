from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any


def test_write_tools_do_not_reference_removed_action_literals(repo_root: Path) -> None:
    write_source = (repo_root / "src" / "mirastack_redfish_mcp" / "tools" / "write.py").read_text(
        encoding="utf-8"
    )
    assert "Task.Abort" not in write_source
    assert '"ResetType": reset_type' in write_source


def test_corpus_conformance_script_passes(repo_root: Path) -> None:
    script = repo_root / "scripts" / "check_corpus_conformance.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout.lower()


def _load_gate(repo_root: Path) -> Any:
    path = repo_root / "scripts" / "check_tool_metadata.py"
    spec = importlib.util.spec_from_file_location("check_tool_metadata_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metadata_gate_rejects_placeholder_param_descriptions(repo_root: Path) -> None:
    """The gate must not accept the generic fallback description as real documentation."""
    import asyncio
    from dataclasses import replace

    from mirastack_redfish_mcp.tools import read

    gate = _load_gate(repo_root)
    # Dropping the curated descriptions makes register_tool fall back to the generic
    # placeholder, which is exactly the defect the gate must catch.
    original = read.READ_TOOL_SPECS["get_system"]
    read.READ_TOOL_SPECS["get_system"] = replace(original, param_descriptions={})
    try:
        errors = asyncio.run(gate._check_metadata())
    finally:
        read.READ_TOOL_SPECS["get_system"] = original

    placeholder_errors = [error for error in errors if "generic placeholder" in error]
    assert placeholder_errors, f"gate did not flag placeholder descriptions; got {errors}"
    assert any("get_system" in error for error in placeholder_errors)
