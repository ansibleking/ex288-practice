#!/usr/bin/env python3
"""Build a compact Redfish schema index from DMTF Redfish-Publications."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

VERSIONED_REF_RE = re.compile(r"/([A-Za-z0-9_]+)\.(v\d+_\d+_\d+)\.json#")
VERSIONED_SCHEMA_RE = re.compile(r"^([A-Za-z0-9_]+)\.v(\d+)_(\d+)_(\d+)\.json$")
REGISTRY_FILE_RE = re.compile(r"^([A-Za-z0-9_]+)\.(\d+)\.(\d+)\.(\d+)\.json$")
LOCAL_DEF_REF_RE = re.compile(r"^#/definitions/([^/]+)$")
RELATIVE_DEF_REF_RE = re.compile(r"^([^#/]+)#/definitions/([^/]+)$")
ABSOLUTE_DEF_REF_RE = re.compile(
    r"^https?://redfish\.dmtf\.org/schemas/v1/([^#/]+)#/definitions/([^/]+)$"
)

JSON_META_FILES = {
    "odata-v4.json",
    "odata.4.0.0.json",
    "redfish-payload-annotations-v1.json",
    "redfish-schema-v1.json",
    "redfish-schema.1.0.0.json",
    "redfish-error.v1_0_2.json",
}

MAX_REF_DEPTH = 8


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _version_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.removeprefix("v").split("_")
    return (int(major), int(minor), int(patch))


def _extract_latest_version(resource_type: str, schema: dict[str, Any]) -> str | None:
    definitions = schema.get("definitions")
    if not isinstance(definitions, dict):
        return None
    root = definitions.get(resource_type)
    if not isinstance(root, dict):
        return None
    any_of = root.get("anyOf")
    if not isinstance(any_of, list):
        return None
    versions: list[str] = []
    for item in any_of:
        if not isinstance(item, dict):
            continue
        ref = item.get("$ref")
        if not isinstance(ref, str):
            continue
        match = VERSIONED_REF_RE.search(ref)
        if match and match.group(1) == resource_type:
            versions.append(match.group(2))
    if not versions:
        return None
    return sorted(versions, key=_version_key)[-1]


class SchemaResolver:
    """Resolve local and cross-file schema references."""

    def __init__(self, json_schema_dir: Path) -> None:
        self._json_schema_dir = json_schema_dir
        self._payload_cache: dict[Path, dict[str, Any]] = {}
        self._definition_cache: dict[tuple[Path, str], dict[str, Any] | None] = {}

    def _load_payload(self, path: Path) -> dict[str, Any] | None:
        if path in self._payload_cache:
            return self._payload_cache[path]
        if not path.exists():
            return None
        payload = _read_json(path)
        self._payload_cache[path] = payload
        return payload

    def _get_definition(self, path: Path, name: str) -> dict[str, Any] | None:
        key = (path, name)
        if key in self._definition_cache:
            return self._definition_cache[key]
        payload = self._load_payload(path)
        if not isinstance(payload, dict):
            self._definition_cache[key] = None
            return None
        definitions = payload.get("definitions")
        if not isinstance(definitions, dict):
            self._definition_cache[key] = None
            return None
        definition = definitions.get(name)
        if not isinstance(definition, dict):
            self._definition_cache[key] = None
            return None
        self._definition_cache[key] = definition
        return definition

    def _parse_ref(self, ref: str, current_file: Path) -> tuple[Path, str] | None:
        local = LOCAL_DEF_REF_RE.match(ref)
        if local is not None:
            return (current_file, local.group(1))
        absolute = ABSOLUTE_DEF_REF_RE.match(ref)
        if absolute is not None:
            return (self._json_schema_dir / absolute.group(1), absolute.group(2))
        relative = RELATIVE_DEF_REF_RE.match(ref)
        if relative is not None:
            return (self._json_schema_dir / relative.group(1), relative.group(2))
        return None

    @staticmethod
    def _unwrap_nullable_any_of(payload: dict[str, Any]) -> dict[str, Any]:
        any_of = payload.get("anyOf")
        if not isinstance(any_of, list):
            return payload
        non_null: list[dict[str, Any]] = []
        for item in any_of:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "null":
                continue
            non_null.append(item)
        if len(non_null) != 1:
            return payload
        merged = dict(non_null[0])
        for key, value in payload.items():
            if key == "anyOf":
                continue
            merged[key] = value
        return merged

    def resolve(
        self,
        candidate: dict[str, Any],
        *,
        current_file: Path,
        visited: set[str] | None = None,
        depth: int = 0,
    ) -> tuple[dict[str, Any], str | None]:
        if depth > MAX_REF_DEPTH:
            return (candidate, None)
        visited_refs = set() if visited is None else set(visited)
        merged_candidate = self._unwrap_nullable_any_of(candidate)
        ref = merged_candidate.get("$ref")
        if not isinstance(ref, str):
            return (merged_candidate, None)
        parsed = self._parse_ref(ref, current_file)
        if parsed is None:
            return (merged_candidate, None)
        ref_path, ref_name = parsed
        canonical_ref = f"{ref_path.name}#/definitions/{ref_name}"
        if canonical_ref in visited_refs:
            return (merged_candidate, canonical_ref)
        target = self._get_definition(ref_path, ref_name)
        if not isinstance(target, dict):
            return (merged_candidate, canonical_ref)
        visited_refs.add(canonical_ref)
        deep_payload, deep_enum_ref = self.resolve(
            target,
            current_file=ref_path,
            visited=visited_refs,
            depth=depth + 1,
        )
        merged: dict[str, Any] = {}
        if isinstance(deep_payload, dict):
            merged.update(deep_payload)
        for key, value in merged_candidate.items():
            if key in {"$ref", "anyOf"}:
                continue
            merged[key] = value
        enum_ref = deep_enum_ref
        if enum_ref is None and isinstance(merged.get("enum"), list):
            enum_ref = canonical_ref
        return (merged, enum_ref)


def _normalize_text_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(item, str):
            out[str(key)] = item
    return out


def _normalize_enum_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
        else:
            out.append(str(item))
    return out


def _inline_enum_ref(current_file: Path, context_path: str) -> str:
    token = context_path.replace("/", ".").replace(" ", "_")
    return f"{current_file.name}#/inline/{token}"


def _intern_enum(
    *,
    enum_table: dict[str, Any],
    enum_ref: str,
    payload: dict[str, Any],
) -> None:
    enum_values = _normalize_enum_values(payload.get("enum"))
    if not enum_values:
        return
    if enum_ref in enum_table:
        return
    entry: dict[str, Any] = {"values": enum_values}
    descriptions = _normalize_text_map(payload.get("enumDescriptions"))
    if descriptions:
        entry["descriptions"] = descriptions
    deprecated = _normalize_text_map(payload.get("enumDeprecated"))
    if deprecated:
        entry["deprecated"] = deprecated
    version_deprecated = _normalize_text_map(payload.get("enumVersionDeprecated"))
    if version_deprecated:
        entry["version_deprecated"] = version_deprecated
    enum_table[enum_ref] = entry


def _distill_property(
    prop_name: str,
    payload: dict[str, Any],
    *,
    current_file: Path,
    resolver: SchemaResolver,
    enum_table: dict[str, Any],
    context_path: str,
) -> dict[str, Any]:
    resolved_payload, resolved_enum_ref = resolver.resolve(payload, current_file=current_file)
    out: dict[str, Any] = {}
    if "type" in resolved_payload:
        out["type"] = resolved_payload["type"]
    if "readonly" in resolved_payload:
        out["readonly"] = bool(resolved_payload["readonly"])
    if "writeOnly" in resolved_payload:
        out["write_only"] = bool(resolved_payload["writeOnly"])
    if "units" in resolved_payload:
        out["units"] = resolved_payload["units"]
    enum_values = _normalize_enum_values(resolved_payload.get("enum"))
    if enum_values:
        enum_ref = resolved_enum_ref or _inline_enum_ref(current_file, context_path)
        _intern_enum(enum_table=enum_table, enum_ref=enum_ref, payload=resolved_payload)
        out["enum_ref"] = enum_ref
    elif "enumDescriptions" in resolved_payload and isinstance(
        resolved_payload["enumDescriptions"], dict
    ):
        out["enum_descriptions"] = resolved_payload["enumDescriptions"]
    if "deprecated" in resolved_payload:
        out["deprecated"] = resolved_payload["deprecated"]
    if "versionDeprecated" in resolved_payload:
        out["version_deprecated"] = resolved_payload["versionDeprecated"]
    if "description" in resolved_payload and isinstance(resolved_payload["description"], str):
        out["description"] = resolved_payload["description"]
    if "excerpt" in resolved_payload:
        out["excerpt"] = resolved_payload["excerpt"]
    if "requiredParameter" in resolved_payload:
        out["required_parameter"] = bool(resolved_payload["requiredParameter"])
    if "pattern" in resolved_payload and isinstance(resolved_payload["pattern"], str):
        out["pattern"] = resolved_payload["pattern"]
    if "format" in resolved_payload and isinstance(resolved_payload["format"], str):
        out["format"] = resolved_payload["format"]
    minimum = resolved_payload.get("minimum")
    if isinstance(minimum, (int, float)):
        out["minimum"] = minimum
    maximum = resolved_payload.get("maximum")
    if isinstance(maximum, (int, float)):
        out["maximum"] = maximum
    if "enumDeprecated" in resolved_payload and isinstance(resolved_payload["enumDeprecated"], dict):
        out["enum_deprecated"] = resolved_payload["enumDeprecated"]
    if "enumVersionDeprecated" in resolved_payload and isinstance(
        resolved_payload["enumVersionDeprecated"], dict
    ):
        out["enum_version_deprecated"] = resolved_payload["enumVersionDeprecated"]
    return out


def _distill_actions(
    root_payload: dict[str, Any],
    *,
    resource_type: str,
    current_file: Path,
    resolver: SchemaResolver,
    enum_table: dict[str, Any],
) -> dict[str, Any]:
    actions_out: dict[str, Any] = {}
    root_properties = root_payload.get("properties")
    if not isinstance(root_properties, dict):
        return actions_out
    actions_candidate = root_properties.get("Actions")
    if not isinstance(actions_candidate, dict):
        return actions_out
    actions_payload, _ = resolver.resolve(actions_candidate, current_file=current_file)
    properties = actions_payload.get("properties")
    if not isinstance(properties, dict):
        return actions_out
    for key, value in properties.items():
        if not isinstance(key, str) or not key.startswith("#"):
            continue
        if not isinstance(value, dict):
            continue
        action_def, _ = resolver.resolve(value, current_file=current_file)
        params_out: dict[str, Any] = {}
        parameters = action_def.get("parameters")
        if isinstance(parameters, dict):
            for param_name, param_payload in parameters.items():
                if not isinstance(param_payload, dict):
                    continue
                params_out[param_name] = _distill_property(
                    param_name,
                    param_payload,
                    current_file=current_file,
                    resolver=resolver,
                    enum_table=enum_table,
                    context_path=f"{resource_type}.actions.{key}.{param_name}",
                )
        display_name = key.removeprefix("#")
        if "." in display_name:
            display_name = display_name.split(".", 1)[1]
        action_out: dict[str, Any] = {
            "description": action_def.get("description"),
            "display_name": display_name,
            "parameters": params_out,
        }
        if "actionResponse" in action_def:
            action_out["action_response"] = action_def.get("actionResponse")
        actions_out[key] = action_out
    return actions_out


def _distill_versioned_schema(
    path: Path,
    resource_type: str,
    *,
    resolver: SchemaResolver,
    enum_table: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = _read_json(path)
    definitions = schema.get("definitions")
    if not isinstance(definitions, dict):
        return ({}, {})
    root_payload = definitions.get(resource_type)
    if not isinstance(root_payload, dict):
        return ({}, {})

    properties_out: dict[str, Any] = {}
    properties = root_payload.get("properties")
    if isinstance(properties, dict):
        for prop_name, prop_payload in properties.items():
            if isinstance(prop_payload, dict):
                properties_out[prop_name] = _distill_property(
                    prop_name,
                    prop_payload,
                    current_file=path,
                    resolver=resolver,
                    enum_table=enum_table,
                    context_path=f"{resource_type}.properties.{prop_name}",
                )
    actions_out = _distill_actions(
        root_payload,
        resource_type=resource_type,
        current_file=path,
        resolver=resolver,
        enum_table=enum_table,
    )
    return (properties_out, actions_out)


def _collect_resource_types(
    json_schema_dir: Path, *, resolver: SchemaResolver, enum_table: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    output: dict[str, Any] = {}
    schema_files = sorted(json_schema_dir.glob("*.json"))
    for path in schema_files:
        name = path.name
        if name in JSON_META_FILES:
            continue
        versioned_match = VERSIONED_SCHEMA_RE.match(name)
        if versioned_match:
            continue
        schema = _read_json(path)
        definitions = schema.get("definitions")
        if not isinstance(definitions, dict):
            continue
        resource_type = path.stem
        root = definitions.get(resource_type)
        if not isinstance(root, dict):
            continue
        uris = root.get("uris")
        if not isinstance(uris, list):
            continue
        latest_version = _extract_latest_version(resource_type, schema)
        properties_out: dict[str, Any] = {}
        actions_out: dict[str, Any] = {}
        if latest_version:
            versioned_path = json_schema_dir / f"{resource_type}.{latest_version}.json"
            if versioned_path.exists():
                properties_out, actions_out = _distill_versioned_schema(
                    versioned_path,
                    resource_type,
                    resolver=resolver,
                    enum_table=enum_table,
                )
        output[resource_type] = {
            "latest_version": latest_version,
            "uris": [str(uri) for uri in uris if isinstance(uri, str)],
            "uris_deprecated": [
                str(uri) for uri in root.get("urisDeprecated", []) if isinstance(uri, str)
            ],
            "insertable": bool(root.get("insertable", False)),
            "updatable": bool(root.get("updatable", False)),
            "deletable": bool(root.get("deletable", False)),
            "properties": properties_out,
            "actions": actions_out,
        }
    return (output, len(schema_files))


def _collect_definition_enums(json_schema_dir: Path, *, enum_table: dict[str, Any]) -> int:
    collected = 0
    for path in sorted(json_schema_dir.glob("*.json")):
        payload = _read_json(path)
        definitions = payload.get("definitions")
        if not isinstance(definitions, dict):
            continue
        for definition_name, definition_payload in definitions.items():
            if not isinstance(definition_name, str) or not isinstance(definition_payload, dict):
                continue
            if not isinstance(definition_payload.get("enum"), list):
                continue
            enum_ref = f"{path.name}#/definitions/{definition_name}"
            if enum_ref in enum_table:
                continue
            _intern_enum(enum_table=enum_table, enum_ref=enum_ref, payload=definition_payload)
            collected += 1
    return collected


def _collect_registries(registry_dir: Path) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    processed = 0
    for path in sorted(registry_dir.glob("*.json")):
        match = REGISTRY_FILE_RE.match(path.name)
        if match is None:
            continue
        payload = _read_json(path)
        if payload.get("Messages") is None:
            continue
        processed += 1
        prefix = str(payload.get("RegistryPrefix") or match.group(1))
        version = str(
            payload.get("RegistryVersion") or f"{match.group(2)}.{match.group(3)}.{match.group(4)}"
        )
        messages_in = payload.get("Messages")
        if not isinstance(messages_in, dict):
            continue
        messages_out: dict[str, Any] = {}
        for key, value in messages_in.items():
            if not isinstance(value, dict):
                continue
            template = value.get("Message")
            if not isinstance(template, str):
                continue
            messages_out[str(key)] = {
                "Message": template,
                "MessageSeverity": value.get("MessageSeverity"),
                "Severity": value.get("Severity"),
                "NumberOfArgs": value.get("NumberOfArgs"),
                "ParamTypes": value.get("ParamTypes"),
                "Resolution": value.get("Resolution"),
            }
        out.setdefault(prefix, {})[version] = {"messages": messages_out}
    return (out, processed)


def _build_uri_template_index(resources: dict[str, Any]) -> list[dict[str, str]]:
    uri_templates: list[dict[str, str]] = []
    for resource_type, payload in resources.items():
        uris = payload.get("uris")
        if isinstance(uris, list):
            for uri in uris:
                if isinstance(uri, str):
                    uri_templates.append({"template": uri, "resource_type": resource_type})
        uris_deprecated = payload.get("uris_deprecated")
        if isinstance(uris_deprecated, list):
            for uri in uris_deprecated:
                if isinstance(uri, str):
                    uri_templates.append(
                        {
                            "template": uri,
                            "resource_type": resource_type,
                            "deprecated": "true",
                        }
                    )
    return uri_templates


def build_index(corpus_dir: Path, *, provenance: dict[str, str]) -> dict[str, Any]:
    json_schema_dir = corpus_dir / "json-schema"
    registry_dir = corpus_dir / "registries"
    if not json_schema_dir.is_dir():
        raise FileNotFoundError(f"json-schema directory not found under {corpus_dir}")
    if not registry_dir.is_dir():
        raise FileNotFoundError(f"registries directory not found under {corpus_dir}")

    resolver = SchemaResolver(json_schema_dir)
    enum_table: dict[str, Any] = {}
    resources, schema_files = _collect_resource_types(
        json_schema_dir, resolver=resolver, enum_table=enum_table
    )
    _collect_definition_enums(json_schema_dir, enum_table=enum_table)
    registries, registry_files = _collect_registries(registry_dir)

    return {
        "source": {
            "corpus": "DMTF Redfish-Publications",
            **provenance,
            "schema_files": schema_files,
            "registry_files": registry_files,
        },
        "resource_types": resources,
        "uri_templates": _build_uri_template_index(resources),
        "registries": registries,
        "enums": enum_table,
    }


def _write_json_gz(path: Path, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    with path.open("wb") as file_handle, gzip.GzipFile(
        fileobj=file_handle, mode="wb", filename="", mtime=0
    ) as gzip_handle:
        gzip_handle.write(data)


def main() -> int:
    # Support both `python tools/build_schema_index.py` and `python -m tools.build_schema_index`.
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.redfish_corpus import CORPUS_REF, CORPUS_URL, CorpusError, ensure_corpus

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        default=os.getenv("REDFISH_CORPUS_DIR") or None,
        help=(
            "Path to an existing Redfish-Publications git checkout. "
            "Omit to clone the pinned ref from GitHub into the corpus cache."
        ),
    )
    parser.add_argument(
        "--corpus-ref",
        default=CORPUS_REF,
        help=f"DMTF publication tag to build from (default: {CORPUS_REF})",
    )
    parser.add_argument(
        "--corpus-cache",
        default=None,
        help="Directory holding one checkout per corpus ref",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Fail instead of cloning when the corpus is not already cached",
    )
    parser.add_argument(
        "--output",
        default="src/mirastack_redfish_mcp/data/redfish_index.json.gz",
        help="Output .json or .json.gz path",
    )
    args = parser.parse_args()

    try:
        corpus, corpus_commit = ensure_corpus(
            ref=args.corpus_ref,
            local=Path(args.corpus) if args.corpus else None,
            cache_dir=Path(args.corpus_cache) if args.corpus_cache else None,
            offline=args.offline,
        )
    except CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Corpus: {corpus} ({args.corpus_ref} @ {corpus_commit[:12]})")
    index = build_index(
        corpus,
        provenance={
            "corpus_url": CORPUS_URL,
            "corpus_ref": args.corpus_ref,
            "corpus_commit": corpus_commit,
        },
    )
    if output.suffix == ".gz":
        _write_json_gz(output, index)
    else:
        output.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote schema index: {output}")
    print(f"Resource types: {len(index['resource_types'])}")
    print(f"URI templates: {len(index['uri_templates'])}")
    print(f"Registry families: {len(index['registries'])}")
    print(f"Enums: {len(index['enums'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
