"""Per-kind scope key contracts for typed work-claim targets.

One table decides which keys a scope object must carry and which it may
carry. Required keys identify the target; optional keys refine it. A
steering seat is the worked case: every seat names its project, and a seat
narrowed to one strategy document also names that document, so both live in
one validated object rather than in a second column or a second claim kind.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

TARGET_KIND_ITEM = "item"
TARGET_KIND_EPIC_TASK = "epic_task"
TARGET_KIND_PROCESS = "process"
TARGET_KIND_STEERING = "steering"
TARGET_KIND_MIGRATION_SERIALIZATION = "migration_serialization"
TARGET_KIND_QA_ADMISSION = "qa_admission"
TARGET_KIND_ROUTE_QUALIFICATION = "route_qualification"
TARGET_KIND_DEPLOY_SERIALIZATION = "deploy_serialization"
ALL_TARGET_KINDS = (
    TARGET_KIND_ITEM,
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_PROCESS,
    TARGET_KIND_STEERING,
    TARGET_KIND_MIGRATION_SERIALIZATION,
    TARGET_KIND_QA_ADMISSION,
    TARGET_KIND_ROUTE_QUALIFICATION,
    TARGET_KIND_DEPLOY_SERIALIZATION,
)

#: The strategy document a steering seat is narrowed to, when it has one.
STEERING_DOCUMENT_KEY = "document"

REQUIRED_SCOPE_KEYS = {
    TARGET_KIND_ITEM: frozenset({"item_id"}),
    TARGET_KIND_EPIC_TASK: frozenset({"epic_id", "task_num"}),
    TARGET_KIND_PROCESS: frozenset({"process_key", "conflict_group"}),
    TARGET_KIND_STEERING: frozenset({"project_id"}),
    TARGET_KIND_MIGRATION_SERIALIZATION: frozenset(
        {"project_id", "model", "item_id"}
    ),
    TARGET_KIND_QA_ADMISSION: frozenset({"machine_id"}),
    TARGET_KIND_ROUTE_QUALIFICATION: frozenset({"project_id", "grant_key"}),
    TARGET_KIND_DEPLOY_SERIALIZATION: frozenset(
        {"project_id", "project_slug"}
    ),
}

OPTIONAL_SCOPE_KEYS = {
    TARGET_KIND_STEERING: frozenset({STEERING_DOCUMENT_KEY}),
}


class TargetValidationError(ValueError):
    """Raised when a typed-target scope fails its kind contract."""


def positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise TargetValidationError(f"{label} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise TargetValidationError(f"{label} must be a positive integer") from exc
    if normalized <= 0:
        raise TargetValidationError(f"{label} must be a positive integer")
    return normalized


def nonempty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TargetValidationError(f"{label} must be non-empty text")
    return value


def _checked_keys(kind: str, raw: Mapping[str, Any]) -> None:
    required = REQUIRED_SCOPE_KEYS[kind]
    optional = OPTIONAL_SCOPE_KEYS.get(kind, frozenset())
    present = frozenset(raw)
    if not required <= present or not present <= (required | optional):
        allowed = (
            f"exactly {sorted(required)}"
            if not optional
            else f"{sorted(required)} plus any of {sorted(optional)}"
        )
        raise TargetValidationError(
            f"{kind} scope requires {allowed}; "
            f"got {sorted(str(key) for key in present)}"
        )


def normalize_scope(kind: str, scope: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and canonicalize one kind-specific scope object."""
    if kind not in ALL_TARGET_KINDS:
        raise TargetValidationError(
            f"target_kind must be one of {ALL_TARGET_KINDS}; got {kind!r}"
        )
    if not isinstance(scope, Mapping):
        raise TargetValidationError("work-claim scope must be a JSON object")
    raw = dict(scope)
    _checked_keys(kind, raw)
    if kind == TARGET_KIND_ITEM:
        return {"item_id": positive_integer(raw["item_id"], "item_id")}
    if kind == TARGET_KIND_EPIC_TASK:
        return {
            "epic_id": positive_integer(raw["epic_id"], "epic_id"),
            "task_num": positive_integer(raw["task_num"], "task_num"),
        }
    if kind == TARGET_KIND_PROCESS:
        return {
            "process_key": nonempty_text(raw["process_key"], "process_key"),
            "conflict_group": nonempty_text(raw["conflict_group"], "conflict_group"),
        }
    if kind == TARGET_KIND_MIGRATION_SERIALIZATION:
        return {
            "project_id": positive_integer(raw["project_id"], "project_id"),
            "model": nonempty_text(raw["model"], "model"),
            "item_id": positive_integer(raw["item_id"], "item_id"),
        }
    if kind == TARGET_KIND_QA_ADMISSION:
        return {"machine_id": nonempty_text(raw["machine_id"], "machine_id")}
    if kind == TARGET_KIND_ROUTE_QUALIFICATION:
        return {
            "project_id": positive_integer(raw["project_id"], "project_id"),
            "grant_key": nonempty_text(raw["grant_key"], "grant_key"),
        }
    if kind == TARGET_KIND_DEPLOY_SERIALIZATION:
        # The slug rides in the scope so the operator key renders without a
        # database read, while exclusivity stays on the project id alone: a
        # rename cannot hand out a second live lock.
        return {
            "project_id": positive_integer(raw["project_id"], "project_id"),
            "project_slug": nonempty_text(raw["project_slug"], "project_slug"),
        }
    steering = {"project_id": positive_integer(raw["project_id"], "project_id")}
    if STEERING_DOCUMENT_KEY in raw:
        steering[STEERING_DOCUMENT_KEY] = nonempty_text(
            raw[STEERING_DOCUMENT_KEY], STEERING_DOCUMENT_KEY
        )
    return steering


__all__ = [
    "ALL_TARGET_KINDS",
    "OPTIONAL_SCOPE_KEYS",
    "REQUIRED_SCOPE_KEYS",
    "STEERING_DOCUMENT_KEY",
    "TARGET_KIND_DEPLOY_SERIALIZATION",
    "TARGET_KIND_EPIC_TASK",
    "TARGET_KIND_ITEM",
    "TARGET_KIND_MIGRATION_SERIALIZATION",
    "TARGET_KIND_PROCESS",
    "TARGET_KIND_QA_ADMISSION",
    "TARGET_KIND_ROUTE_QUALIFICATION",
    "TARGET_KIND_STEERING",
    "TargetValidationError",
    "nonempty_text",
    "normalize_scope",
    "positive_integer",
]
