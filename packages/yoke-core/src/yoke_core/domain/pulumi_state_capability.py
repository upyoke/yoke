"""Validation and generic-surface guards for Pulumi state settings."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_core.domain.projects_pulumi_state_migration_marker import (
    MIGRATION_MARKERS_KEY,
    validate_markers,
)


CAPABILITY_TYPE = "pulumi-state"
STACK_STATE_KEY = "stack_state"
COMPONENT_TYPE_ALIASES_KEY = "component_type_aliases"
_ENTRY_KEYS = frozenset({"secrets_provider", "encrypted_key"})
_STRING_KEYS = frozenset({
    "deploy_namespace", "infra_stack_name", "kms_key_alias",
    "runner_fleet_stack_name", "state_bucket", "vps_stack_name",
})
_PUBLIC_MERGE_KEYS = _STRING_KEYS | {"stacks", COMPONENT_TYPE_ALIASES_KEY}
_ALLOWED_KEYS = _PUBLIC_MERGE_KEYS | {
    STACK_STATE_KEY, MIGRATION_MARKERS_KEY,
}


def validate_json_string(raw_json: str) -> str:
    """Validate a full Pulumi-state capability document canonically."""
    try:
        document = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("pulumi-state settings must be valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("pulumi-state settings must be a JSON object")
    unknown = sorted(set(document) - _ALLOWED_KEYS)
    if unknown:
        raise ValueError(
            "pulumi-state settings contain unknown fields: " + ", ".join(unknown)
        )
    for key in sorted(_STRING_KEYS & set(document)):
        value = document[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"pulumi-state {key} must be a non-empty string")
        document[key] = value.strip()
    if "stacks" in document:
        raw_stacks = document["stacks"]
        if not isinstance(raw_stacks, list):
            raise ValueError("pulumi-state stacks must be a list")
        stacks = [str(value or "").strip() for value in raw_stacks]
        if any(not value for value in stacks) or len(stacks) != len(set(stacks)):
            raise ValueError("pulumi-state stacks must be non-empty and unique")
        document["stacks"] = stacks
    if COMPONENT_TYPE_ALIASES_KEY in document:
        document[COMPONENT_TYPE_ALIASES_KEY] = validate_component_type_aliases(
            document[COMPONENT_TYPE_ALIASES_KEY]
        )
    raw_state = document.get(STACK_STATE_KEY)
    if raw_state is not None:
        document[STACK_STATE_KEY] = validate_stack_state(raw_state)
    if MIGRATION_MARKERS_KEY in document:
        document[MIGRATION_MARKERS_KEY] = validate_markers(
            document[MIGRATION_MARKERS_KEY]
        )
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def validate_component_type_aliases(raw: Any) -> dict[str, list[str]]:
    """Validate project-owned legacy ComponentResource type aliases."""
    if not isinstance(raw, Mapping):
        raise ValueError("pulumi-state component_type_aliases must be an object")
    result: dict[str, list[str]] = {}
    for raw_kind, raw_aliases in raw.items():
        kind = str(raw_kind or "").strip()
        if not kind or not isinstance(raw_aliases, list):
            raise ValueError(
                "pulumi-state component_type_aliases entries require a "
                "non-empty stack kind and a list"
            )
        aliases = [str(value or "").strip() for value in raw_aliases]
        if any(not value for value in aliases) or len(aliases) != len(set(aliases)):
            raise ValueError(
                "pulumi-state component type aliases must be non-empty and unique"
            )
        result[kind] = aliases
    return result


def validate_stack_state(raw_state: Any) -> dict[str, dict[str, str]]:
    """Return the canonical exact shape for per-stack operator state."""
    if not isinstance(raw_state, Mapping):
        raise ValueError("pulumi-state stack_state must be an object")
    result: dict[str, dict[str, str]] = {}
    for raw_name, raw_entry in raw_state.items():
        name = str(raw_name or "").strip()
        if not name:
            raise ValueError("pulumi-state stack names must be non-empty")
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != _ENTRY_KEYS:
            raise ValueError(
                "pulumi-state stack entries must contain only "
                "secrets_provider and encrypted_key"
            )
        entry: dict[str, str] = {}
        for key in sorted(_ENTRY_KEYS):
            value = raw_entry[key]
            if isinstance(value, (dict, list)) or value is None:
                raise ValueError(
                    "pulumi-state stack entry values must be non-empty scalars"
                )
            text = str(value).strip()
            if not text:
                raise ValueError(
                    "pulumi-state stack entry values must be non-empty scalars"
                )
            entry[key] = text
        result[name] = entry
    return result


def reject_generic_read(cap_type: str) -> str:
    selected = str(cap_type or "").strip()
    if selected == CAPABILITY_TYPE:
        raise ValueError(
            "pulumi-state aggregate reads are closed; declare non-sensitive "
            "stacks/backend fields with `yoke projects capability-settings "
            "merge`, initialize an exact declared stack with `yoke pulumi "
            "exec`, then use `yoke projects pulumi-stack-config get`"
        )
    return selected


def reject_generic_full_write(cap_type: str) -> str:
    selected = str(cap_type or "").strip()
    if selected == CAPABILITY_TYPE:
        raise ValueError(
            "pulumi-state full settings writes are closed; use typed "
            "top-level merges or the Pulumi state migration surface"
        )
    return selected


def validate_merge_assignments(
    cap_type: str, assignments: Mapping[str, Any]
) -> str:
    selected = str(cap_type or "").strip()
    if selected != CAPABILITY_TYPE:
        return selected
    closed = sorted(
        str(path) for path in assignments
        if str(path) not in _PUBLIC_MERGE_KEYS
    )
    if closed:
        raise ValueError(
            "pulumi-state generic merges allow only known non-sensitive "
            "top-level fields; use the typed Pulumi state migration surface "
            "for operator state"
        )
    return selected


__all__ = [
    "CAPABILITY_TYPE",
    "COMPONENT_TYPE_ALIASES_KEY",
    "reject_generic_full_write",
    "reject_generic_read",
    "validate_json_string",
    "validate_component_type_aliases",
    "validate_merge_assignments",
    "validate_stack_state",
]
