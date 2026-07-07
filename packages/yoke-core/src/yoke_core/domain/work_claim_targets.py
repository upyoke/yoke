"""Typed work-claim target helpers shared by every claim mutation path.

A ``work_claims`` row carries exactly one populated target — item,
epic_task, or process — with the schema CHECK enforcing the shape.
This module wraps that vocabulary so every caller (CLI, domain layer,
harness, render, scheduler, verify) speaks one validated language
instead of hand-rolling INSERT/UPDATE/SELECT shapes per surface.

Vocabulary:

- ``TARGET_KIND_ITEM`` — claim on a real backlog item; ``item_id`` set.
- ``TARGET_KIND_EPIC_TASK`` — claim on a single epic task;
  ``epic_id`` + ``task_num`` set.
- ``TARGET_KIND_PROCESS`` — claim on a recurring process key;
  ``process_key`` + ``conflict_group`` set.

The ``WorkClaimTarget`` dataclass validates kind-specific population on
construction so callers cannot smuggle a malformed target past the type
system.  ``insert_columns`` returns a column-name → value mapping that
maps 1:1 onto the post-cutover ``work_claims`` schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from yoke_core.domain.work_processes import conflict_group_for

TARGET_KIND_ITEM = "item"
TARGET_KIND_EPIC_TASK = "epic_task"
TARGET_KIND_PROCESS = "process"
ALL_TARGET_KINDS = (TARGET_KIND_ITEM, TARGET_KIND_EPIC_TASK, TARGET_KIND_PROCESS)


class TargetValidationError(ValueError):
    """Raised when a typed-target payload fails the per-kind invariants."""


@dataclass(frozen=True)
class WorkClaimTarget:
    """One typed work-claim target with kind-specific population."""

    kind: str
    item_id: Optional[int] = None
    epic_id: Optional[int] = None
    task_num: Optional[int] = None
    process_key: Optional[str] = None
    conflict_group: Optional[str] = None
    process_project: Optional[str] = None

    def __post_init__(self) -> None:
        validate_target(self)

    def insert_columns(self) -> Dict[str, Any]:
        return {
            "target_kind": self.kind,
            "item_id": self.item_id,
            "epic_id": self.epic_id,
            "task_num": self.task_num,
            "process_key": self.process_key,
            "conflict_group": self.conflict_group,
        }

    def render(self) -> str:
        if self.kind == TARGET_KIND_ITEM:
            return f"YOK-{self.item_id}"
        if self.kind == TARGET_KIND_EPIC_TASK:
            return f"YOK-{self.epic_id} task {self.task_num}"
        return f"process:{self.process_key}"


def make_item_target(item_id: int) -> WorkClaimTarget:
    return WorkClaimTarget(kind=TARGET_KIND_ITEM, item_id=int(item_id))


def make_epic_task_target(epic_id: int, task_num: int) -> WorkClaimTarget:
    return WorkClaimTarget(
        kind=TARGET_KIND_EPIC_TASK, epic_id=int(epic_id), task_num=int(task_num),
    )


def make_process_target(process_key: str, project: str) -> WorkClaimTarget:
    """Build a process target with the conflict group resolved from registry."""
    group = conflict_group_for(process_key, project)
    return WorkClaimTarget(
        kind=TARGET_KIND_PROCESS,
        process_key=process_key,
        conflict_group=group,
        process_project=project,
    )


def from_row(row: Mapping[str, Any]) -> WorkClaimTarget:
    """Reconstruct a target from a ``work_claims`` row mapping.

    Used by render/board surfaces that need to project the typed shape
    back to operator-facing strings.
    """
    kind = row.get("target_kind")
    if kind == TARGET_KIND_ITEM:
        return WorkClaimTarget(kind=TARGET_KIND_ITEM, item_id=int(row["item_id"]))
    if kind == TARGET_KIND_EPIC_TASK:
        return WorkClaimTarget(
            kind=TARGET_KIND_EPIC_TASK,
            epic_id=int(row["epic_id"]),
            task_num=int(row["task_num"]),
        )
    if kind == TARGET_KIND_PROCESS:
        return WorkClaimTarget(
            kind=TARGET_KIND_PROCESS,
            process_key=row["process_key"],
            conflict_group=row["conflict_group"],
        )
    raise TargetValidationError(
        f"unknown target_kind {kind!r}; expected one of {ALL_TARGET_KINDS}"
    )


def validate_target(target: WorkClaimTarget) -> None:
    """Enforce the kind-specific population invariants the schema CHECK
    will also reject.  Surface failures here as ``TargetValidationError``
    so callers can produce structured error JSON before the DB rejects."""
    if target.kind not in ALL_TARGET_KINDS:
        raise TargetValidationError(
            f"target_kind must be one of {ALL_TARGET_KINDS}; got {target.kind!r}"
        )
    if target.kind == TARGET_KIND_ITEM:
        if target.item_id is None:
            raise TargetValidationError("item target requires item_id")
        if (target.epic_id is not None or target.task_num is not None
                or target.process_key is not None
                or target.conflict_group is not None
                or target.process_project is not None):
            raise TargetValidationError(
                "item target must leave epic_id/task_num/process_key/"
                "conflict_group/process_project NULL"
            )
        return
    if target.kind == TARGET_KIND_EPIC_TASK:
        if target.epic_id is None or target.task_num is None:
            raise TargetValidationError(
                "epic_task target requires both epic_id and task_num"
            )
        if (target.item_id is not None or target.process_key is not None
                or target.conflict_group is not None
                or target.process_project is not None):
            raise TargetValidationError(
                "epic_task target must leave item_id/process_key/"
                "conflict_group/process_project NULL"
            )
        return
    # process
    if not target.process_key or not target.conflict_group:
        raise TargetValidationError(
            "process target requires both process_key and conflict_group"
        )
    if (target.item_id is not None or target.epic_id is not None
            or target.task_num is not None):
        raise TargetValidationError(
            "process target must leave item_id/epic_id/task_num NULL"
        )


__all__ = [
    "ALL_TARGET_KINDS",
    "TARGET_KIND_EPIC_TASK",
    "TARGET_KIND_ITEM",
    "TARGET_KIND_PROCESS",
    "TargetValidationError",
    "WorkClaimTarget",
    "from_row",
    "make_epic_task_target",
    "make_item_target",
    "make_process_target",
    "validate_target",
]
