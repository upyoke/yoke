"""The one declared browser step schema.

Validation and the browser runtime both read ``browser_step_schema.json``.
A step that fails here cannot be executed. The Node interpreter in
``browser_runtime/src/step-schema.js`` applies the same declaration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Optional

SCHEMA_RESOURCE = "browser_step_schema.json"


@dataclass(frozen=True)
class StepSchemaViolation:
    """One step the declared schema will not execute."""

    code: str
    message: str


def schema_bytes() -> bytes:
    """Return the declaration bytes, from the package file or installed data."""
    beside = Path(__file__).with_name(SCHEMA_RESOURCE)
    if beside.is_file():
        return beside.read_bytes()
    resource = files("yoke_contracts").joinpath(SCHEMA_RESOURCE)
    try:
        return resource.read_bytes()
    except OSError as exc:
        raise RuntimeError(
            "browser_step_schema_missing: "
            f"yoke_contracts/{SCHEMA_RESOURCE} is not installed ({exc}). "
            "Reinstall yoke-contracts; the schema is package data."
        ) from None


def load_schema() -> dict[str, Any]:
    """Return the declared schema document shipped with this package."""
    raw = schema_bytes().decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(
            "browser_step_schema_invalid: "
            f"yoke_contracts/{SCHEMA_RESOURCE} must be a JSON object."
        )
    return parsed


_SCHEMA = load_schema()

SHARED_STEP_KEYS = frozenset(_SCHEMA["shared_keys"])
ACTION_STEP_KEYS = {
    action: frozenset(spec["keys"]) for action, spec in _SCHEMA["actions"].items()
}


def defined_keys_for_action(action: str) -> frozenset[str]:
    """Return the keys *action* honours, including shared optional fields."""
    extra = ACTION_STEP_KEYS.get(action)
    if extra is None:
        return SHARED_STEP_KEYS
    return SHARED_STEP_KEYS | extra


def declared_schema_help() -> str:
    """Publish the declared schema for ``yoke qa browser step --help``."""
    lines = [
        "Execute one JSON browser step. Exploratory agents choose and "
        "sequence calls at runtime; this command does not author a case.",
        "",
        "Declared browser step schema:",
    ]
    for action in sorted(ACTION_STEP_KEYS):
        keys = ", ".join(sorted(ACTION_STEP_KEYS[action]))
        lines.append(f"  {action}: {keys}")
    lines.append("Shared keys: " + ", ".join(sorted(SHARED_STEP_KEYS)))
    aliases = _SCHEMA.get("aliases") or {}
    rendered = ", ".join(f"{key} -> {aliases[key]}" for key in sorted(aliases))
    lines.append(f"Refused aliases: {rendered}")
    retired = _SCHEMA.get("retired_actions") or {}
    for action, replacement in sorted(retired.items()):
        lines.append(f"Retired action {action}: use {replacement}")
    lines.append(
        "A screenshot step requires capture=true and then records an "
        "artifact. target must be a non-empty string selector, not an "
        "object. On assert, value is refused; use expected."
    )
    return "\n".join(lines)


def _defined_list(action: str) -> str:
    return ", ".join(sorted(defined_keys_for_action(action)))


def _honour(
    action: str,
    index: int,
    keys: list[str],
    *,
    use: Optional[str] = None,
) -> str:
    labelled = ", ".join(repr(key) for key in keys)
    noun = "key" if len(keys) == 1 else "keys"
    use_clause = f"; use {use!r}" if use is not None else ""
    return (
        f"Browser {action} step {index} does not honour {noun} "
        f"{labelled}{use_clause}. Defined keys: {_defined_list(action)}"
    )


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _field_violation(
    action: str,
    index: int,
    step: dict[str, Any],
    field: str,
    rule: dict[str, Any],
) -> Optional[StepSchemaViolation]:
    present = field in step
    value = step.get(field)
    if rule.get("type") == "true":
        if value is not True:
            return StepSchemaViolation(
                "screenshot_capture_required",
                f"Browser screenshot step {index} requires capture=true so "
                "it records an artifact. Set 'capture' to true, or remove "
                "the screenshot step.",
            )
        return None
    if rule.get("type") == "object":
        if not isinstance(value, dict):
            return StepSchemaViolation(
                "step_field_invalid",
                f"Browser {action} step {index} requires a {field} object.",
            )
        return None
    if rule.get("type") != "non_empty_string":
        return None
    if isinstance(value, dict):
        return StepSchemaViolation(
            "step_field_invalid",
            f"Browser {action} step {index} field {field!r} must be a "
            "non-empty string, not an object.",
        )
    if (rule.get("required") or present) and not _non_empty_text(value):
        return StepSchemaViolation(
            "step_field_invalid",
            f"Browser {action} step {index} requires a non-empty {field}.",
        )
    return None


def step_schema_violation(
    index: int,
    step: dict[str, Any],
) -> Optional[StepSchemaViolation]:
    """Return the first reason *step* cannot be executed, if any."""
    action = step.get("action")
    if not isinstance(action, str) or not action.strip():
        return StepSchemaViolation(
            "step_action_missing",
            f"Browser step {index} must have an action field",
        )
    retired = (_SCHEMA.get("retired_actions") or {}).get(action)
    if retired is not None:
        return StepSchemaViolation(
            "step_action_retired",
            f"Browser step {index} action {action!r} is not executable; use {retired}.",
        )
    spec = (_SCHEMA.get("actions") or {}).get(action)
    if not isinstance(spec, dict):
        defined = ", ".join(sorted(ACTION_STEP_KEYS))
        return StepSchemaViolation(
            "step_action_unknown",
            f"Unknown action: {action!r} at step {index}. Defined actions: {defined}",
        )
    aliases = _SCHEMA.get("aliases") or {}
    alias_hits = sorted(key for key in step if key in aliases)
    if alias_hits:
        key = alias_hits[0]
        return StepSchemaViolation(
            "step_key_unrecognized",
            _honour(action, index, [key], use=str(aliases[key])),
        )
    reject = spec.get("reject_keys") or {}
    rejected = sorted(key for key in step if key in reject)
    if rejected:
        key = rejected[0]
        return StepSchemaViolation(
            "step_key_unrecognized",
            _honour(action, index, [key], use=str(reject[key])),
        )
    allowed = defined_keys_for_action(action)
    unknown = sorted(key for key in step if key not in allowed)
    if unknown:
        return StepSchemaViolation(
            "step_key_unrecognized",
            _honour(action, index, unknown),
        )
    fields = spec.get("fields") or {}
    for field, rule in fields.items():
        if isinstance(rule, dict):
            found = _field_violation(action, index, step, field, rule)
            if found is not None:
                return found
    require_any = spec.get("require_any") or []
    if require_any and not any(
        _non_empty_text(step.get(field)) for field in require_any
    ):
        named = ", ".join(str(field) for field in require_any)
        return StepSchemaViolation(
            "step_require_any",
            f"Browser {action} step {index} requires one of: {named}.",
        )
    return None


__all__ = [
    "ACTION_STEP_KEYS",
    "SCHEMA_RESOURCE",
    "SHARED_STEP_KEYS",
    "StepSchemaViolation",
    "declared_schema_help",
    "defined_keys_for_action",
    "load_schema",
    "schema_bytes",
    "step_schema_violation",
]
