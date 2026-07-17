"""Durable non-sensitive convergence evidence for Pulumi state moves."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any


MIGRATION_MARKERS_KEY = "migration_receipts"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def destination_has_entries(
    destination: Mapping[str, Any] | None, requested: Sequence[str]
) -> bool:
    return destination is not None and all(name in destination for name in requested)


def remove_source_state(settings: dict[str, Any]) -> None:
    pulumi = dict(settings.get("pulumi") or {})
    pulumi.pop("stack_state", None)
    if pulumi:
        settings["pulumi"] = pulumi
    else:
        settings.pop("pulumi", None)


def marker_matches(
    settings: Mapping[str, Any], site_id: str, stack_names: Sequence[str]
) -> bool:
    markers = settings.get(MIGRATION_MARKERS_KEY)
    if not isinstance(markers, Mapping):
        return False
    marker = markers.get(str(site_id))
    return (
        isinstance(marker, Mapping)
        and marker.get("stack_names") == sorted(stack_names)
    )


def set_marker(
    settings: dict[str, Any], site_id: str, stack_names: Sequence[str]
) -> None:
    raw = settings.get(MIGRATION_MARKERS_KEY)
    markers = dict(raw) if isinstance(raw, Mapping) else {}
    markers[str(site_id)] = {"stack_names": sorted(stack_names)}
    settings[MIGRATION_MARKERS_KEY] = markers


def validate_markers(raw: Any) -> dict[str, dict[str, list[str]]]:
    if not isinstance(raw, Mapping):
        raise ValueError("pulumi-state migration_receipts must be an object")
    result: dict[str, dict[str, list[str]]] = {}
    for raw_site, raw_marker in raw.items():
        site = str(raw_site or "").strip()
        if not site or not isinstance(raw_marker, Mapping):
            raise ValueError("pulumi-state migration receipt entries are invalid")
        if set(raw_marker) != {"stack_names"}:
            raise ValueError(
                "pulumi-state migration receipts contain only stack_names"
            )
        names = raw_marker["stack_names"]
        if not isinstance(names, list):
            raise ValueError("pulumi-state migration stack_names must be a list")
        normalized = [str(name or "").strip() for name in names]
        if (
            any(not name for name in normalized)
            or len(normalized) != len(set(normalized))
            or normalized != sorted(normalized)
        ):
            raise ValueError(
                "pulumi-state migration stack_names must be sorted and unique"
            )
        result[site] = {"stack_names": normalized}
    return result


__all__ = [
    "MIGRATION_MARKERS_KEY",
    "canonical_json",
    "destination_has_entries",
    "marker_matches",
    "remove_source_state",
    "set_marker",
    "validate_markers",
]
