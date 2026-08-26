"""Typed work-claim targets stored as one canonical JSON scope.

Every work_claims row uses the same storage pair: target_kind names the
target vocabulary and scope contains the kind-specific JSON object. This
module is the sole shape authority for construction, validation, SQL
matching, rendering, and row decoding.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.sql_json import json_get
from yoke_core.domain.work_processes import conflict_group_for

TARGET_KIND_ITEM = "item"
TARGET_KIND_EPIC_TASK = "epic_task"
TARGET_KIND_PROCESS = "process"
TARGET_KIND_STEERING = "steering"
ALL_TARGET_KINDS = (
    TARGET_KIND_ITEM,
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_PROCESS,
    TARGET_KIND_STEERING,
)

_SCOPE_KEYS = {
    TARGET_KIND_ITEM: frozenset({"item_id"}),
    TARGET_KIND_EPIC_TASK: frozenset({"epic_id", "task_num"}),
    TARGET_KIND_PROCESS: frozenset({"process_key", "conflict_group"}),
    TARGET_KIND_STEERING: frozenset({"project_id"}),
}


class TargetValidationError(ValueError):
    """Raised when a typed-target scope fails its kind contract."""


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise TargetValidationError(f"{label} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise TargetValidationError(f"{label} must be a positive integer") from exc
    if normalized <= 0:
        raise TargetValidationError(f"{label} must be a positive integer")
    return normalized


def _nonempty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TargetValidationError(f"{label} must be non-empty text")
    return value


def normalize_scope(kind: str, scope: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and canonicalize one kind-specific scope object."""
    if kind not in ALL_TARGET_KINDS:
        raise TargetValidationError(
            f"target_kind must be one of {ALL_TARGET_KINDS}; got {kind!r}"
        )
    if not isinstance(scope, Mapping):
        raise TargetValidationError("work-claim scope must be a JSON object")
    raw = dict(scope)
    expected = _SCOPE_KEYS[kind]
    if frozenset(raw) != expected:
        raise TargetValidationError(
            f"{kind} scope requires exactly {sorted(expected)}; "
            f"got {sorted(str(key) for key in raw)}"
        )
    if kind == TARGET_KIND_ITEM:
        return {"item_id": _positive_integer(raw["item_id"], "item_id")}
    if kind == TARGET_KIND_EPIC_TASK:
        return {
            "epic_id": _positive_integer(raw["epic_id"], "epic_id"),
            "task_num": _positive_integer(raw["task_num"], "task_num"),
        }
    if kind == TARGET_KIND_PROCESS:
        return {
            "process_key": _nonempty_text(raw["process_key"], "process_key"),
            "conflict_group": _nonempty_text(raw["conflict_group"], "conflict_group"),
        }
    return {"project_id": _positive_integer(raw["project_id"], "project_id")}


def decode_scope(raw: Any) -> Dict[str, Any]:
    """Decode a stored JSON scope without assigning it a target kind."""
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise TargetValidationError("work-claim scope must contain JSON") from exc
    else:
        value = raw
    if not isinstance(value, Mapping):
        raise TargetValidationError("work-claim scope must contain a JSON object")
    return dict(value)


def encode_scope(scope: Mapping[str, Any]) -> str:
    """Return stable compact JSON for identity comparisons and storage."""
    return json.dumps(dict(scope), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class WorkClaimTarget:
    """One target kind plus its validated scope object."""

    kind: str
    scope: Mapping[str, Any]
    process_project: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", normalize_scope(self.kind, self.scope))

    @property
    def item_id(self) -> Optional[int]:
        value = self.scope.get("item_id")
        return int(value) if value is not None else None

    @property
    def epic_id(self) -> Optional[int]:
        value = self.scope.get("epic_id")
        return int(value) if value is not None else None

    @property
    def task_num(self) -> Optional[int]:
        value = self.scope.get("task_num")
        return int(value) if value is not None else None

    @property
    def process_key(self) -> Optional[str]:
        value = self.scope.get("process_key")
        return str(value) if value is not None else None

    @property
    def conflict_group(self) -> Optional[str]:
        value = self.scope.get("conflict_group")
        return str(value) if value is not None else None

    @property
    def project_id(self) -> Optional[int]:
        value = self.scope.get("project_id")
        return int(value) if value is not None else None

    def scope_json(self) -> str:
        return encode_scope(self.scope)

    def insert_columns(self) -> Dict[str, Any]:
        return {"target_kind": self.kind, "scope": self.scope_json()}

    def descriptor(self) -> Dict[str, Any]:
        """Return the canonical JSON boundary shape for this target."""
        return {"target_kind": self.kind, "scope": dict(self.scope)}

    def render(self) -> str:
        from yoke_core.domain.project_identity_item_ref import item_ref_for_id

        if self.kind == TARGET_KIND_ITEM:
            return item_ref_for_id(int(self.item_id))
        if self.kind == TARGET_KIND_EPIC_TASK:
            return f"{item_ref_for_id(int(self.epic_id))} task {self.task_num}"
        if self.kind == TARGET_KIND_STEERING:
            return f"steering for project {self.project_id}"
        return f"process:{self.process_key}"


def make_item_target(item_id: int) -> WorkClaimTarget:
    return WorkClaimTarget(TARGET_KIND_ITEM, {"item_id": int(item_id)})


def make_epic_task_target(epic_id: int, task_num: int) -> WorkClaimTarget:
    return WorkClaimTarget(
        TARGET_KIND_EPIC_TASK,
        {"epic_id": int(epic_id), "task_num": int(task_num)},
    )


def make_process_target(process_key: str, project: str) -> WorkClaimTarget:
    """Build a process target with its registered project conflict group."""
    return WorkClaimTarget(
        TARGET_KIND_PROCESS,
        {
            "process_key": process_key,
            "conflict_group": conflict_group_for(process_key, project),
        },
        process_project=project,
    )


def make_steering_target(project_id: int) -> WorkClaimTarget:
    return WorkClaimTarget(TARGET_KIND_STEERING, {"project_id": int(project_id)})


def from_row(row: Mapping[str, Any]) -> WorkClaimTarget:
    """Reconstruct and validate a target from a work_claims row."""
    return WorkClaimTarget(
        kind=str(row["target_kind"]),
        scope=decode_scope(row["scope"]),
    )


def item_id_from_row(row: Mapping[str, Any]) -> Optional[int]:
    """Return the item id when ``row`` carries an item target."""
    target = from_row(row)
    return target.item_id if target.kind == TARGET_KIND_ITEM else None


def validate_target(target: WorkClaimTarget) -> None:
    """Re-run domain validation for a target received across a boundary."""
    normalize_scope(target.kind, target.scope)


def scope_text_sql(conn: Any, column_expr: str, key: str) -> str:
    """Return a portable SQL expression reading one scope value as text."""
    if db_backend.connection_is_postgres(conn):
        return json_get(column_expr, f"$.{key}")
    return f"json_extract({column_expr}, '$.{key}')"


def scope_int_sql(conn: Any, column_expr: str, key: str) -> str:
    """Return a portable SQL expression reading one scope value as integer."""
    return f"CAST({scope_text_sql(conn, column_expr, key)} AS INTEGER)"


def exact_match_clause(
    conn: Any,
    target: WorkClaimTarget,
    *,
    alias: str = "",
) -> tuple[str, list[Any]]:
    """Return SQL and params matching one exact canonical target."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    prefix = f"{alias}." if alias else ""
    return (
        f"{prefix}target_kind = {p} AND {prefix}scope = {p}",
        [target.kind, target.scope_json()],
    )


def conflict_match_clause(
    conn: Any,
    target: WorkClaimTarget,
    *,
    alias: str = "",
) -> tuple[str, list[Any]]:
    """Return SQL and params matching the target's exclusivity unit."""
    if target.kind != TARGET_KIND_PROCESS:
        return exact_match_clause(conn, target, alias=alias)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    prefix = f"{alias}." if alias else ""
    conflict_expr = scope_text_sql(conn, f"{prefix}scope", "conflict_group")
    return (
        f"{prefix}target_kind = {p} AND {conflict_expr} = {p}",
        [TARGET_KIND_PROCESS, target.conflict_group],
    )


__all__ = [
    "ALL_TARGET_KINDS",
    "TARGET_KIND_EPIC_TASK",
    "TARGET_KIND_ITEM",
    "TARGET_KIND_PROCESS",
    "TARGET_KIND_STEERING",
    "TargetValidationError",
    "WorkClaimTarget",
    "conflict_match_clause",
    "decode_scope",
    "encode_scope",
    "exact_match_clause",
    "from_row",
    "item_id_from_row",
    "make_epic_task_target",
    "make_item_target",
    "make_process_target",
    "make_steering_target",
    "normalize_scope",
    "scope_int_sql",
    "scope_text_sql",
    "validate_target",
]
