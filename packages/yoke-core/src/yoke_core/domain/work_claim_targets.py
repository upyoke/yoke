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

from yoke_core.domain.work_processes import conflict_group_for

TARGET_KIND_ITEM = "item"
TARGET_KIND_EPIC_TASK = "epic_task"
TARGET_KIND_PROCESS = "process"
TARGET_KIND_STEERING = "steering"
TARGET_KIND_MIGRATION_SERIALIZATION = "migration_serialization"
TARGET_KIND_QA_ADMISSION = "qa_admission"
TARGET_KIND_ROUTE_QUALIFICATION = "route_qualification"
ALL_TARGET_KINDS = (
    TARGET_KIND_ITEM,
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_PROCESS,
    TARGET_KIND_STEERING,
    TARGET_KIND_MIGRATION_SERIALIZATION,
    TARGET_KIND_QA_ADMISSION,
    TARGET_KIND_ROUTE_QUALIFICATION,
)

#: Sticky kinds outlive the taking session (a migration or host suite in
#: flight); reclaim is the audited operator release, never an auto-sweep.
STICKY_TARGET_KINDS = frozenset(
    {TARGET_KIND_MIGRATION_SERIALIZATION, TARGET_KIND_QA_ADMISSION}
)

_SCOPE_KEYS = {
    TARGET_KIND_ITEM: frozenset({"item_id"}),
    TARGET_KIND_EPIC_TASK: frozenset({"epic_id", "task_num"}),
    TARGET_KIND_PROCESS: frozenset({"process_key", "conflict_group"}),
    TARGET_KIND_STEERING: frozenset({"project_id"}),
    TARGET_KIND_MIGRATION_SERIALIZATION: frozenset(
        {"project_id", "model", "item_id"}
    ),
    TARGET_KIND_QA_ADMISSION: frozenset({"machine_id"}),
    TARGET_KIND_ROUTE_QUALIFICATION: frozenset({"project_id", "grant_key"}),
}

def is_sticky(kind: str) -> bool:
    """Return True when this kind survives session end and the sweep."""
    return kind in STICKY_TARGET_KINDS


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
    if kind == TARGET_KIND_MIGRATION_SERIALIZATION:
        return {
            "project_id": _positive_integer(raw["project_id"], "project_id"),
            "model": _nonempty_text(raw["model"], "model"),
            "item_id": _positive_integer(raw["item_id"], "item_id"),
        }
    if kind == TARGET_KIND_QA_ADMISSION:
        return {"machine_id": _nonempty_text(raw["machine_id"], "machine_id")}
    if kind == TARGET_KIND_ROUTE_QUALIFICATION:
        return {
            "project_id": _positive_integer(raw["project_id"], "project_id"),
            "grant_key": _nonempty_text(raw["grant_key"], "grant_key"),
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

    @property
    def model(self) -> Optional[str]:
        value = self.scope.get("model")
        return str(value) if value is not None else None

    @property
    def machine_id(self) -> Optional[str]:
        value = self.scope.get("machine_id")
        return str(value) if value is not None else None

    @property
    def grant_key(self) -> Optional[str]:
        value = self.scope.get("grant_key")
        return str(value) if value is not None else None

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
        if self.kind == TARGET_KIND_MIGRATION_SERIALIZATION:
            return (
                f"migration territory {self.model} "
                f"(project {self.project_id}, item "
                f"{item_ref_for_id(int(self.item_id))})"
            )
        if self.kind == TARGET_KIND_QA_ADMISSION:
            return f"test machine {self.machine_id}"
        if self.kind == TARGET_KIND_ROUTE_QUALIFICATION:
            return f"route qualification for project {self.project_id}"
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


def make_migration_serialization_target(
    project_id: int,
    model: str,
    item_id: int,
) -> WorkClaimTarget:
    """Build the per-model migration-territory target for one owning item."""
    return WorkClaimTarget(
        TARGET_KIND_MIGRATION_SERIALIZATION,
        {
            "project_id": int(project_id),
            "model": str(model),
            "item_id": int(item_id),
        },
    )


def make_qa_admission_target(machine_id: str) -> WorkClaimTarget:
    """Build the target serializing one physical test machine."""
    return WorkClaimTarget(TARGET_KIND_QA_ADMISSION, {"machine_id": str(machine_id)})


def make_route_qualification_target(
    project_id: int,
    grant_key: str,
) -> WorkClaimTarget:
    """Build the target holding one private-route qualification grant."""
    return WorkClaimTarget(
        TARGET_KIND_ROUTE_QUALIFICATION,
        {"project_id": int(project_id), "grant_key": str(grant_key)},
    )


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


# SQL helpers stay lazy so schema_init can import kinds without a cycle.
def __getattr__(name: str):
    if name not in {
        "conflict_match_clause", "exact_match_clause",
        "scope_int_sql", "scope_text_sql",
    }:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from yoke_core.domain import work_claim_target_sql as sql
    value = getattr(sql, name)
    globals()[name] = value
    return value

__all__ = [
    "ALL_TARGET_KINDS",
    "STICKY_TARGET_KINDS",
    "TARGET_KIND_EPIC_TASK",
    "TARGET_KIND_ITEM",
    "TARGET_KIND_MIGRATION_SERIALIZATION",
    "TARGET_KIND_PROCESS",
    "TARGET_KIND_QA_ADMISSION",
    "TARGET_KIND_ROUTE_QUALIFICATION",
    "TARGET_KIND_STEERING",
    "TargetValidationError",
    "WorkClaimTarget",
    "conflict_match_clause",
    "decode_scope",
    "encode_scope",
    "exact_match_clause",
    "from_row",
    "is_sticky",
    "item_id_from_row",
    "make_epic_task_target",
    "make_item_target",
    "make_migration_serialization_target",
    "make_process_target",
    "make_qa_admission_target",
    "make_route_qualification_target",
    "make_steering_target",
    "normalize_scope",
    "scope_int_sql",
    "scope_text_sql",
    "validate_target",
]
