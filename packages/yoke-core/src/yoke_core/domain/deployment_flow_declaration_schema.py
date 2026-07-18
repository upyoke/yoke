"""Validation and normalization for project-owned deployment flows."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from yoke_core.domain import json_helper
from yoke_core.domain.deployment_flow_state import (
    FLOW_STATUS_ACTIVE,
    validate_flow_status,
)
from yoke_core.domain.flow_validation import validate_stages
from yoke_contracts.project_contract.deployment_flows import (
    DECLARATION_SCHEMA,
    EMPTY_DECLARATION_TEXT,
)


_FLOW_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_DOCUMENT_KEYS = frozenset({
    "schema",
    "flows",
    "default_flow",
    "retire_if_present",
})
_FLOW_KEYS = frozenset({
    "id",
    "name",
    "description",
    "stages",
    "on_failure",
    "target_env",
    "done_description",
    "status",
})


@dataclass(frozen=True)
class FlowDeclaration:
    id: str
    name: str
    description: str
    stages: str
    on_failure: str
    target_env: str | None
    done_description: str | None
    status: str


@dataclass(frozen=True)
class FlowDeclarationDocument:
    flows: tuple[FlowDeclaration, ...]
    retire_if_present: tuple[str, ...]
    default_flow: str | None
    default_flow_declared: bool


def empty_declaration_text() -> str:
    """Return the neutral project-contract seed document."""
    return EMPTY_DECLARATION_TEXT


def normalize_document(document: object) -> FlowDeclarationDocument:
    """Validate and normalize a declaration document before any DB write."""
    if not isinstance(document, Mapping):
        raise ValueError("deployment flow declaration root must be an object")
    unknown = set(document) - _DOCUMENT_KEYS
    if unknown:
        raise ValueError(
            f"deployment flow declaration has unknown keys: {sorted(unknown)}"
        )
    if document.get("schema") != DECLARATION_SCHEMA:
        raise ValueError(
            f"deployment flow declaration schema must be {DECLARATION_SCHEMA}"
        )
    raw_flows = document.get("flows")
    if not isinstance(raw_flows, list):
        raise ValueError("deployment flow declaration flows must be an array")

    flows = tuple(
        _normalize_flow(raw, index) for index, raw in enumerate(raw_flows)
    )
    ids = [flow.id for flow in flows]
    names = [flow.name for flow in flows]
    if len(ids) != len(set(ids)):
        raise ValueError("deployment flow declaration contains duplicate flow ids")
    if len(names) != len(set(names)):
        raise ValueError("deployment flow declaration contains duplicate flow names")

    raw_retire = document.get("retire_if_present", [])
    if not isinstance(raw_retire, list):
        raise ValueError("retire_if_present must be an array")
    retire_if_present = tuple(
        _retirement_id(raw, index) for index, raw in enumerate(raw_retire)
    )
    if len(retire_if_present) != len(set(retire_if_present)):
        raise ValueError("retire_if_present contains duplicate flow ids")
    overlap = sorted(set(ids) & set(retire_if_present))
    if overlap:
        raise ValueError(f"declared flows cannot also be retired: {overlap}")

    default_declared = "default_flow" in document
    default_flow = document.get("default_flow")
    if default_declared:
        if not isinstance(default_flow, str) or not default_flow.strip():
            raise ValueError("default_flow must be a non-empty string when present")
        default_flow = default_flow.strip()
    else:
        default_flow = None
    return FlowDeclarationDocument(
        flows=flows,
        retire_if_present=retire_if_present,
        default_flow=default_flow,
        default_flow_declared=default_declared,
    )


def _retirement_id(raw: object, index: int) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(
            f"retire_if_present entry {index} must be a non-empty string"
        )
    flow_id = raw.strip()
    if not _FLOW_ID_RE.fullmatch(flow_id):
        raise ValueError(
            f"retire_if_present entry {index} must be lowercase slug-shape"
        )
    return flow_id


def _normalize_flow(raw: object, index: int) -> FlowDeclaration:
    if not isinstance(raw, Mapping):
        raise ValueError(f"flow {index} must be an object")
    unknown = set(raw) - _FLOW_KEYS
    if unknown:
        raise ValueError(f"flow {index} has unknown keys: {sorted(unknown)}")
    flow_id = _required_string(raw, "id", index)
    if not _FLOW_ID_RE.fullmatch(flow_id):
        raise ValueError(
            f"flow {index} id must be lowercase slug-shape "
            "(letters, digits, '-', '_')"
        )
    stages = raw.get("stages")
    if not isinstance(stages, list):
        raise ValueError(f"flow {index} stages must be an array")
    stages_json = json_helper.dumps_compact(stages)
    validate_stages(stages_json)
    return FlowDeclaration(
        id=flow_id,
        name=_required_string(raw, "name", index),
        description=_optional_string(raw, "description", index, default=""),
        stages=stages_json,
        on_failure=_optional_string(raw, "on_failure", index, default="halt"),
        target_env=_nullable_string(raw, "target_env", index),
        done_description=_nullable_string(raw, "done_description", index),
        status=validate_flow_status(str(raw.get("status", FLOW_STATUS_ACTIVE))),
    )


def _required_string(raw: Mapping[str, Any], key: str, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"flow {index} {key} must be a non-empty string")
    return value.strip()


def _optional_string(
    raw: Mapping[str, Any], key: str, index: int, *, default: str,
) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"flow {index} {key} must be a string")
    return value


def _nullable_string(
    raw: Mapping[str, Any], key: str, index: int,
) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"flow {index} {key} must be a string or null")
    return value


__all__ = [
    "FlowDeclaration",
    "FlowDeclarationDocument",
    "empty_declaration_text",
    "normalize_document",
]
