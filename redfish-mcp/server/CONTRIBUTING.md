# Contributing

## Mirror Contribution Policy

This GitHub repository is a public **read-only mirror** of the private GitLab source of truth.

- GitHub issues are welcome.
- GitHub pull requests cannot be merged and will be overwritten by mirror sync.
- To contribute code, send a patch to `security@mirastacklabs.ai` or use the public GitLab MR flow when announced.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Schema Corpus

The distilled schema artifact in `src/mirastack_redfish_mcp/data/redfish_index.json.gz` is generated from the [DMTF Redfish-Publications](https://github.com/DMTF/Redfish-Publications) corpus. The builder clones that repository itself, so no sibling checkout or manual download is required:

```bash
make build-index
```

The corpus is pinned to one DMTF publication tag by `CORPUS_REF` in `tools/redfish_corpus.py`, and checkouts are cached per ref under `${XDG_CACHE_HOME:-~/.cache}/mirastack-redfish-mcp/corpus` (override with `REDFISH_CORPUS_CACHE`). Pinning is what lets CI rebuild the index and compare it byte for byte against the committed artifact; a floating `main` would make every build produce a different wheel.

To build from an existing checkout instead of cloning, pass `--corpus` or set `REDFISH_CORPUS_DIR`. The builder verifies that the checkout sits exactly on the pinned ref and refuses to run otherwise, so a stale local clone cannot silently produce a mismatched artifact.

### Refreshing the corpus

`make corpus-latest` reports whether DMTF has published a newer release; CI runs the same check as the non-blocking `corpus-freshness` job. Refreshing is a deliberate, reviewed change because it rewrites the shipped index:

```bash
make refresh-corpus CORPUS_REF=2026.2   # rebuild the index from the new release
# then set CORPUS_REF = "2026.2" in tools/redfish_corpus.py
make verify
```

`tests/test_corpus.py` fails if the pin and the committed artifact disagree, so the two cannot drift apart. Also update the corpus version quoted in `README.md`.

## Code Quality

Run before submitting a patch or GitLab merge request:

```bash
ruff check src tests tools
mypy src tests tools
pytest -q
python scripts/check_tool_metadata.py
MIRASTACK_REDFISH_WRITE_MODE=full python scripts/check_tool_metadata.py
python scripts/check_corpus_conformance.py
```

`make verify` runs lint, typecheck, tests, and both gate scripts in one shot; run it before submitting changes.

Corpus-backed mockup tests skip when the corpus cannot be fetched (offline development). CI sets `REDFISH_REQUIRE_CORPUS=1`, which turns that skip into a failure so the coverage cannot silently vanish from a pipeline.

## Test Expectations

- Add or update tests for all behavior changes.
- Preserve synthetic coverage for:
  - `Members@odata.nextLink` pagination
  - `If-Match` and `412 PreconditionFailed` flows
  - `202 Accepted` task-monitor polling
- Keep mockup-walk tests passing against the current corpus snapshot.

## Design Constraints

- Do not hardcode vendor-specific URI assumptions when standard links are available.
- Prefer service-advertised metadata (`@Redfish.ActionInfo`, `@Redfish.AllowableValues`, `@Redfish.Settings`) over guessed behavior.
- Keep mutating behavior behind write tiers and dry-run confirmation.
- Do not hardcode Redfish enum values in tool code; source allowable values from the compiled schema index.
- Every tool must ship with:
  - non-empty title
  - non-empty description
  - `ToolAnnotations`
  - description for every input parameter
- Every tool description must include:
  - `Returns:` one-line output-shape summary
  - `Example:` one compact invocation example, at most 110 characters, omitting any argument the tool auto-resolves and keeping `confirm=false` on mutating tools
- Every tool must declare a toolset category so `MIRASTACK_REDFISH_TOOL_PROFILE` / `MIRASTACK_REDFISH_TOOLSETS` can gate registration.
- `Returns:` is a contract, not a summary. Name the actual response keys, and if the payload goes through `maybe_truncate_list`, append `LIST_ENVELOPE` so callers know to read `.items`.
- Never name another tool in a description, parameter, or the server instructions unless that tool is guaranteed to be advertised in every configuration that advertises the text. If a cross-tool reference is unavoidable, add the dependency to `TOOLSET_COMPANIONS` in `src/mirastack_redfish_mcp/config.py`. `scripts/check_tool_metadata.py` checks this across all three profiles, both write modes, and every single-toolset configuration.
- Annotations describe reality. Set `destructive_hint` on anything that accepts a caller-chosen URI and body, and `open_world_hint=false` on tools that touch no remote service.
- Parameter descriptions must say something the parameter name does not. The generic `_default_param_description` fallback is rejected by the metadata gate.
- For free-form object parameters (`dict[str, Any]` style), provide schema examples via `Field(examples=[...])` and keep property names corpus-grounded.
- Any new literal action name or payload parameter key must pass `scripts/check_corpus_conformance.py`.

## Registry CLI Warning

- Install the official MCP Registry publisher via Homebrew: `brew install mcp-publisher`.
- Do **not** use `npx mcp-publisher` or `pip install mcp-publisher`; those names can resolve to unrelated third-party packages.

## Commit and PR Guidelines

- Keep commits focused by concern (client, tools, schema index, tests, docs, CI).
- Include protocol-level reasoning in PR descriptions when changing write behavior.
- If upgrading DMTF corpus version, regenerate and commit the distilled index in the same PR.

