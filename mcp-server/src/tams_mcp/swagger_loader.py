from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MUTATING_KEYWORDS = (
    "insert",
    "delete",
    "approve",
    "reject",
    "upload",
    "addupdate",
    "update",
    "credit",
    "change",
    "post",
    "set",
    "rolldelete",
    "userdelete",
)


@dataclass
class GeneratedTool:
    name: str
    description: str
    method: str
    path: str
    tag: str = ""
    body_schema: str = ""
    parameters: list[dict[str, Any]] = field(default_factory=list)


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text[:60] or "tool"


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        return {}
    node: Any = spec
    for part in ref.lstrip("#/").split("/"):
        node = node.get(part, {})
    return node if isinstance(node, dict) else {}


def _schema_properties(spec: dict[str, Any], schema: dict[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])

    priority = (
        "fromDate",
        "toDate",
        "payCode",
        "paycode",
        "companyCode",
        "company",
        "department",
        "departmentCode",
        "enrollmentCode",
        "ssn",
        "name",
        "status",
        "reportType",
        "presentcardno",
        "dashboardDate",
    )
    props = schema.get("properties", {})
    ordered_keys = [k for k in priority if k in props] + [k for k in props if k not in priority]

    result: list[dict[str, Any]] = []
    for key in ordered_keys[:limit]:
        prop = props[key]
        if "$ref" in prop:
            prop = _resolve_ref(spec, prop["$ref"])
        result.append(
            {
                "name": key,
                "in": "body",
                "required": key in schema.get("required", []),
                "description": prop.get("description", ""),
                "type": prop.get("type", "string"),
                "format": prop.get("format"),
            }
        )
    return result


def _param_schema(param: dict[str, Any]) -> dict[str, Any]:
    schema = param.get("schema") or {}
    return {
        "name": param["name"],
        "in": param.get("in", "query"),
        "required": bool(param.get("required")),
        "description": param.get("description", ""),
        "type": schema.get("type", "string"),
        "format": schema.get("format"),
        "enum": schema.get("enum"),
    }


def _request_body_schema(spec: dict[str, Any], operation: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    for media in ("application/json", "text/json", "application/*+json", "application/json-patch+json"):
        if media in content:
            schema = content[media].get("schema", {})
            ref = schema.get("$ref", "")
            schema_name = ref.split("/")[-1] if ref else ""
            return schema_name, _schema_properties(spec, schema)
    return "", []


def _is_read_query(path: str, operation: dict[str, Any]) -> bool:
    action = path.rsplit("/", 1)[-1]
    if re.match(r"^(Add|Insert|Delete|Update|Approve|Reject|Upload|Set|RollDelete|UserDelete)", action):
        return False

    blob = f"{path} {operation.get('operationId', '')} {operation.get('summary', '')}".lower()
    if any(word in blob for word in MUTATING_KEYWORDS):
        return False
    return any(
        word in blob
        for word in (
            "get",
            "bind",
            "list",
            "report",
            "dashboard",
            "balance",
            "attendance",
            "leave",
            "employee",
            "search",
            "details",
        )
    )


def load_tools_from_swagger(
    spec_path: Path,
    *,
    max_tools: int = 60,
    include_tags: list[str] | None = None,
) -> list[GeneratedTool]:
    if not spec_path.exists():
        return []

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    paths: dict[str, Any] = spec.get("paths", {})
    tools: list[GeneratedTool] = []
    tag_filter = {t.lower() for t in (include_tags or [])}

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method.lower() not in {"get", "post"}:
                continue

            tags = operation.get("tags", [])
            tag = tags[0] if tags else "Untagged"
            if tag_filter and tag.lower() not in tag_filter:
                continue
            if not _is_read_query(path, operation):
                continue

            operation_id = operation.get("operationId")
            summary = operation.get("summary") or operation.get("description") or path.rsplit("/", 1)[-1]
            name = _slugify(operation_id or f"{tag}_{path}")

            params = [_param_schema(p) for p in operation.get("parameters", [])]
            body_schema, body_params = _request_body_schema(spec, operation)
            params.extend(body_params)

            tools.append(
                GeneratedTool(
                    name=name,
                    description=f"{summary.strip()} [{tag}]",
                    method=method.upper(),
                    path=path,
                    tag=tag,
                    body_schema=body_schema,
                    parameters=params,
                )
            )

    tools.sort(key=lambda t: (t.tag, t.path))
    return tools[:max_tools]
