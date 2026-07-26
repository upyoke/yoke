"""Canonical encoding and validation errors for stored workflow definitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


class WorkflowRegistryError(RuntimeError):
    """A requested registry operation cannot preserve registry invariants."""


def canonical_definition_json(definition: Mapping[str, Any]) -> str:
    """Serialize a definition into the stable digest and storage form."""
    return json.dumps(
        definition,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def definition_digest(definition: Mapping[str, Any]) -> str:
    """Return the SHA-256 digest of the canonical definition JSON."""
    encoded = canonical_definition_json(definition).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def decode_definition(raw: Any) -> dict[str, Any]:
    """Decode one stored workflow definition object."""
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise WorkflowRegistryError(
            "stored workflow definition is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise WorkflowRegistryError("stored workflow definition is not an object")
    return value


__all__ = [
    "WorkflowRegistryError",
    "canonical_definition_json",
    "decode_definition",
    "definition_digest",
]
