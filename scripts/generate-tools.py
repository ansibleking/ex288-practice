#!/usr/bin/env python3
"""Generate a tool manifest from swagger.json for review."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

from tams_mcp.swagger_loader import load_tools_from_swagger


def main() -> None:
    spec = ROOT / "swagger.json"
    tools = load_tools_from_swagger(spec, max_tools=100)
    out = ROOT / "specs" / "generated-tools.json"
    out.write_text(
        json.dumps([t.__dict__ for t in tools], indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(tools)} tools to {out}")


if __name__ == "__main__":
    main()
