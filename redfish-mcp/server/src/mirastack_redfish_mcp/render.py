"""Token-efficient payload rendering helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def compact_resource(resource: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact yet useful subset of a Redfish resource payload."""
    keep_keys = (
        "@odata.id",
        "@odata.type",
        "Id",
        "Name",
        "Description",
        "Status",
        "Health",
        "State",
        "Message",
        "MessageId",
        "Severity",
        "TaskState",
        "TaskStatus",
        "PercentComplete",
    )
    out: dict[str, Any] = {}
    for key in keep_keys:
        if key in resource:
            out[key] = resource[key]
    return out


# Identity plus hardware-descriptor properties shared across the component collections walked
# by get_component_inventory. Every name is validated against the schema corpus by
# scripts/check_corpus_conformance.py, so this list cannot drift from DSP8010.
COMPONENT_IDENTITY_KEYS: tuple[str, ...] = (
    "@odata.id",
    "@odata.type",
    "Id",
    "Name",
    "Status",
)

COMPONENT_DESCRIPTOR_KEYS: tuple[str, ...] = (
    "Manufacturer",
    "Model",
    "SerialNumber",
    "PartNumber",
    "SparePartNumber",
    "SKU",
    "FirmwareVersion",
    "Location",
    "TotalCores",
    "TotalThreads",
    "ProcessorType",
    "MaxSpeedMHz",
    "Socket",
    "CapacityMiB",
    "MemoryDeviceType",
    "OperatingSpeedMhz",
    "RankCount",
    "BaseModuleType",
    "MACAddress",
    "PermanentMACAddress",
    "SpeedMbps",
    "LinkStatus",
    "DeviceType",
    "PCIeInterface",
    "Drives",
    "Volumes",
)

# Resource types whose members get_component_inventory walks. The descriptor keys above must
# each exist on at least one of these types.
COMPONENT_RESOURCE_TYPES: tuple[str, ...] = (
    "Processor",
    "Memory",
    "Storage",
    "EthernetInterface",
    "PCIeDevice",
)


def compact_component(resource: Mapping[str, Any]) -> dict[str, Any]:
    """Return identity plus hardware-descriptor fields for one component resource."""
    out: dict[str, Any] = {}
    for key in COMPONENT_IDENTITY_KEYS + COMPONENT_DESCRIPTOR_KEYS:
        if key in resource:
            out[key] = resource[key]
    return out


def maybe_truncate_list(items: list[Any], max_items: int = 100) -> dict[str, Any]:
    """Bound large lists returned to models without losing context."""
    total = len(items)
    if total <= max_items:
        return {"items": items, "total": total, "truncated": False}
    return {"items": items[:max_items], "total": total, "truncated": True}
