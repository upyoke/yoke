"""Describe and select independently executable QA case chains."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.qa_latest_execution import latest_verdict_executions
from yoke_core.domain.qa_plan_partition_chains import Partition, roster_partitions
from yoke_core.domain.qa_plan_partition_custody import (
    PartitionScope,
    case_identity,
    held_partition_cases,
    partition_unavailable,
)


@dataclass(frozen=True)
class PartitionView:
    partition: Partition
    state: str
    holder: dict[str, Any] | None = None
    blocked_by: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        part = self.partition
        return {
            "key": part.key,
            "state": self.state,
            "kind": part.kind,
            "hosts": list(part.hosts),
            "cases": [
                {
                    "case_key": row["case_key"],
                    "baseline_position": row["baseline_position"],
                    **({"requirement_id": int(row["requirement_id"])} if row.get("requirement_id") else {}),
                }
                for row in part.roster
            ],
            "blocked_by": list(self.blocked_by),
            **(
                {"execution_id": self.holder["id"], "session_id": self.holder["session_id"]}
                if self.holder is not None
                else {}
            ),
        }


def partition_views(
    conn: Any,
    scope: PartitionScope,
    roster: list[dict[str, Any]],
    *,
    passed: set,
    failed: set,
) -> list[PartitionView]:
    """Grade whole partitions against current settlements and live custody."""
    partitions = roster_partitions(
        roster, standalone=scope.standalone_plan_id is not None,
        item_lane=scope.item_id is not None,
    )
    held = held_partition_cases(conn, scope)
    views = []
    for part in partitions:
        identities = {case_identity(row, scope) for row in part.roster}
        holder = next((held[identity] for identity in identities if identity in held), None)
        if holder is not None:
            state = "held"
        elif identities <= passed:
            state = "passed"
        elif (identities - passed) & failed:
            state = "failed"
        else:
            state = "lane" if part.kind == "lane" else "free"
        views.append(PartitionView(part, state, holder))
    settled = {view.partition.key for view in views if view.state == "passed"}
    return [
        PartitionView(view.partition, "blocked", blocked_by=blocked)
        if view.state in {"free", "lane", "failed"} and (
            blocked := tuple(key for key in view.partition.predecessors if key not in settled)
        )
        else view
        for view in views
    ]


def scoped_partition_views(
    conn: Any, scope: PartitionScope, roster: list[dict[str, Any]]
) -> list[PartitionView]:
    if not roster:
        return []
    if scope.item_id is not None:
        from yoke_core.domain.qa_plan_item_target_partition import candidate_passed_requirements

        _, passed = candidate_passed_requirements(conn, roster, item_id=scope.item_id)
    else:
        from yoke_core.domain.qa_plan_run_target_partition import target_passed_requirements

        passed = target_passed_requirements(
            conn,
            roster,
            deployment_run_id=scope.deployment_run_id,
            deployment_stage=scope.deployment_stage,
            deployment_member_item_id=scope.deployment_member_item_id,
        )
    attempts = latest_verdict_executions(conn, [int(row["requirement_id"]) for row in roster])
    failed = {
        requirement for requirement, attempt in attempts.items()
        if attempt.get("verdict") == "fail"
    }
    return partition_views(conn, scope, roster, passed=passed, failed=failed)


def select_partition(
    views: list[PartitionView],
    *,
    key: str | None,
    session_id: str,
    requirement_id: int | None = None,
    allow_failed: bool = False,
) -> PartitionView | None:
    """Select an owed partition, or the same session's already frozen work."""
    selected = [
        view for view in views
        if (key is None or view.partition.key == key)
        and (
            requirement_id is None
            or any(int(row["requirement_id"]) == requirement_id for row in view.partition.roster)
        )
    ]
    for view in selected:
        if view.holder is not None and str(view.holder["session_id"]) == session_id:
            return view
    for view in selected:
        if view.state in {"free", "lane"} or (allow_failed and view.state == "failed"):
            return view
    if key is not None or requirement_id is not None or any(v.state != "passed" for v in selected):
        view = selected[0] if selected else None
        if view is None:
            reason = "no longer matches the owed cases"
        elif view.holder is not None:
            reason = (
                f"is held by execution {view.holder['id']} in session "
                f"{view.holder['session_id']}"
            )
        elif view.state == "blocked":
            reason = f"waits for partitions {', '.join(view.blocked_by)}"
        else:
            reason = f"is {view.state}"
        raise partition_unavailable(key or (view.partition.key if view else "<selected>"), reason)
    return None
