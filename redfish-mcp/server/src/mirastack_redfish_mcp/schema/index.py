"""Schema index loader for distilled Redfish metadata."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResourceTypeInfo:
    """Distilled metadata for one Redfish resource type."""

    name: str
    latest_version: str | None
    uris: list[str]
    uris_deprecated: list[str]
    insertable: bool
    updatable: bool
    deletable: bool
    actions: dict[str, Any]
    properties: dict[str, Any]


@dataclass(frozen=True)
class EnumInfo:
    """Interned enum metadata from the schema corpus."""

    ref: str
    values: list[str]
    descriptions: dict[str, str]
    deprecated: dict[str, str]
    version_deprecated: dict[str, str]


class SchemaIndex:
    """In-memory wrapper over the compiled schema index artifact."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        resources = data.get("resource_types", {})
        enums = data.get("enums", {})
        self.resource_types: dict[str, ResourceTypeInfo] = {}
        self.enums: dict[str, EnumInfo] = {}
        if isinstance(resources, dict):
            for name, payload in resources.items():
                if not isinstance(payload, dict):
                    continue
                self.resource_types[name] = ResourceTypeInfo(
                    name=name,
                    latest_version=(
                        str(payload.get("latest_version"))
                        if payload.get("latest_version") is not None
                        else None
                    ),
                    uris=list(payload.get("uris", [])),
                    uris_deprecated=list(payload.get("uris_deprecated", [])),
                    insertable=bool(payload.get("insertable", False)),
                    updatable=bool(payload.get("updatable", False)),
                    deletable=bool(payload.get("deletable", False)),
                    actions=dict(payload.get("actions", {})),
                    properties=dict(payload.get("properties", {})),
                )
        if isinstance(enums, dict):
            for ref, payload in enums.items():
                if not isinstance(ref, str) or not isinstance(payload, dict):
                    continue
                values = payload.get("values")
                descriptions = payload.get("descriptions")
                deprecated = payload.get("deprecated")
                version_deprecated = payload.get("version_deprecated")
                self.enums[ref] = EnumInfo(
                    ref=ref,
                    values=list(values) if isinstance(values, list) else [],
                    descriptions=(
                        {str(k): str(v) for k, v in descriptions.items() if isinstance(v, str)}
                        if isinstance(descriptions, dict)
                        else {}
                    ),
                    deprecated=(
                        {str(k): str(v) for k, v in deprecated.items() if isinstance(v, str)}
                        if isinstance(deprecated, dict)
                        else {}
                    ),
                    version_deprecated=(
                        {
                            str(k): str(v)
                            for k, v in version_deprecated.items()
                            if isinstance(v, str)
                        }
                        if isinstance(version_deprecated, dict)
                        else {}
                    ),
                )

    @classmethod
    def from_path(cls, path: str | Path) -> SchemaIndex:
        p = Path(path)
        if p.suffix == ".gz":
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
        else:
            payload = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_payload(payload)

    @classmethod
    def from_bytes(cls, data: bytes, *, gzipped: bool) -> SchemaIndex:
        if gzipped:
            payload = json.loads(gzip.decompress(data).decode("utf-8"))
        else:
            payload = json.loads(data.decode("utf-8"))
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: Any) -> SchemaIndex:
        if not isinstance(payload, dict):
            raise ValueError("schema index payload must be a JSON object")
        return cls(payload)

    def get_resource(self, resource_type: str) -> ResourceTypeInfo | None:
        return self.resource_types.get(resource_type)

    def get_enum(self, enum_ref: str) -> EnumInfo | None:
        return self.enums.get(enum_ref)

    def resolve_property_enum(
        self, resource_type: str, property_name: str
    ) -> EnumInfo | None:
        resource = self.get_resource(resource_type)
        if resource is None:
            return None
        prop = resource.properties.get(property_name)
        if not isinstance(prop, dict):
            return None
        enum_ref = prop.get("enum_ref")
        if not isinstance(enum_ref, str):
            return None
        return self.get_enum(enum_ref)

    def resolve_action_parameter_enum(
        self, resource_type: str, action_key: str, parameter_name: str
    ) -> EnumInfo | None:
        resource = self.get_resource(resource_type)
        if resource is None:
            return None
        action = resource.actions.get(action_key)
        if not isinstance(action, dict):
            return None
        parameters = action.get("parameters")
        if not isinstance(parameters, dict):
            return None
        parameter = parameters.get(parameter_name)
        if not isinstance(parameter, dict):
            return None
        enum_ref = parameter.get("enum_ref")
        if not isinstance(enum_ref, str):
            return None
        return self.get_enum(enum_ref)
