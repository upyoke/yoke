"""Validation for the Pulumi state capability's backend settings.

The capability names where a project's Pulumi state lives (``state_bucket``),
the KMS key ``init`` pins (``kms_key_alias``), the resource naming namespace,
and project-owned legacy component type aliases.
It holds nothing secret: each stack's ``secretsprovider`` and
``encryptedkey`` live in the project's checked-in stack file.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


CAPABILITY_TYPE = "pulumi-state"
COMPONENT_TYPE_ALIASES_KEY = "component_type_aliases"
_STRING_KEYS = frozenset({
    "deploy_namespace", "kms_key_alias",
    "state_bucket",
})
_ALLOWED_KEYS = _STRING_KEYS | {COMPONENT_TYPE_ALIASES_KEY}


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
            "pulumi-state settings contain unknown fields: "
            + ", ".join(unknown)
            + "; allowed fields: "
            + ", ".join(sorted(_ALLOWED_KEYS))
        )
    for key in sorted(_STRING_KEYS & set(document)):
        value = document[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"pulumi-state {key} must be a non-empty string")
        document[key] = value.strip()
    if COMPONENT_TYPE_ALIASES_KEY in document:
        document[COMPONENT_TYPE_ALIASES_KEY] = validate_component_type_aliases(
            document[COMPONENT_TYPE_ALIASES_KEY]
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


__all__ = [
    "CAPABILITY_TYPE",
    "COMPONENT_TYPE_ALIASES_KEY",
    "validate_component_type_aliases",
    "validate_json_string",
]
