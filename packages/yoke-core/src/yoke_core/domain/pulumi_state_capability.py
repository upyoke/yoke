"""Validation and generic-surface guards for Pulumi state settings."""

from __future__ import annotations

import json
from typing import Any, Mapping


CAPABILITY_TYPE = "pulumi-state"
STACK_STATE_KEY = "stack_state"
_ENTRY_KEYS = frozenset({"secrets_provider", "encrypted_key"})


def validate_json_string(raw_json: str) -> str:
    """Validate a full Pulumi-state capability document canonically."""
    try:
        document = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("pulumi-state settings must be valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("pulumi-state settings must be a JSON object")
    raw_state = document.get(STACK_STATE_KEY)
    if raw_state is not None:
        document[STACK_STATE_KEY] = validate_stack_state(raw_state)
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


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
            "pulumi-state settings are stack-scoped; use "
            "`yoke projects pulumi-stack-config get`"
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
    sensitive = sorted(
        str(path) for path in assignments
        if str(path) == STACK_STATE_KEY
        or str(path).startswith(f"{STACK_STATE_KEY}.")
    )
    if sensitive:
        raise ValueError(
            "pulumi-state stack_state is closed on the generic merge surface; "
            "use the typed Pulumi state migration surface"
        )
    return selected


__all__ = [
    "CAPABILITY_TYPE",
    "reject_generic_full_write",
    "reject_generic_read",
    "validate_json_string",
    "validate_merge_assignments",
    "validate_stack_state",
]
