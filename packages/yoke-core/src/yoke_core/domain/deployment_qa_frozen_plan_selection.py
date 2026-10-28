"""Resolve unretracted frozen requirements and plans for a deployment QA stage."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
from yoke_core.domain.deployment_qa_source_plan_refresh import source_refreshed_plan
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql


Refresh = Callable[[dict[str, Any]], dict[str, Any]]


def requirement_applies(
    requirement: Mapping[str, Any], target: Mapping[str, Any]
) -> bool:
    """Select only post-deploy obligations declared for this destination."""
    if str(requirement.get("qa_phase") or "") != "post_deploy":
        return False
    environment = target.get("environment")
    name = (
        str(environment.get("name") or "").strip()
        if isinstance(environment, Mapping)
        else ""
    )
    declared = str(requirement.get("target_env") or "").strip()
    return not declared or declared == name


def member_requirements(
    conn: Any, subject: Mapping[str, Any], *, target: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Read frozen item cases, while honoring later source withdrawals."""
    snapshot = subject.get("member_snapshot")
    if not isinstance(snapshot, Mapping):
        return []
    requirements = [
        dict(requirement)
        for requirement in snapshot.get("requirements") or []
        if isinstance(requirement, Mapping)
        and requirement.get("plan_id") is None
        and requirement_applies(requirement, target)
    ]
    if not requirements:
        return []
    ids = tuple(int(requirement["id"]) for requirement in requirements)
    from yoke_core.domain.deployment_qa_presentation_facts import (
        withdrawn_requirement_ids,
    )

    withdrawn_ids = withdrawn_requirement_ids(conn, ids)
    if withdrawn_ids is None:
        withdrawn = query_rows(
            conn,
            f"SELECT id FROM qa_requirements WHERE id IN ({','.join('%s' for _ in ids)}) "
            f"AND NOT ({unretracted_requirement_sql(conn)})",
            ids,
        )
        withdrawn_ids = {int(row["id"]) for row in withdrawn}
    return [
        requirement
        for requirement in requirements
        if int(requirement["id"]) not in withdrawn_ids
    ]


def _flow_plan(subject: Mapping[str, Any], refresh: Refresh) -> list[dict[str, Any]]:
    stage = str(subject["stage"]["name"])
    return [
        refresh(dict(selection))
        for selection in subject["flow_snapshot"].get("selections") or []
        if isinstance(selection, Mapping) and str(selection.get("stage") or "") == stage
    ]


def frozen_stage_plans(
    conn: Any,
    subject: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    admitted: list[dict[str, Any]],
    lock_plans: bool = True,
) -> list[dict[str, Any]]:
    """Keep plan-owned obligations on their plan's ordered snapshot path."""
    from yoke_core.domain.deployment_qa_snapshot_selection import (
        incomplete_snapshot,
        materialized_plan_ids,
        require_complete_snapshot,
    )

    historical: set[int] | None = None

    def materialized() -> set[int]:
        nonlocal historical
        if historical is None:
            historical = materialized_plan_ids(conn, subject)
        return historical

    def refresh(value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value.get("plan"), Mapping):
            return value
        return source_refreshed_plan(conn, subject, value, materialized=materialized)

    # Post-deploy plans never ride a member: they run as plan groups
    # (:mod:`deployment_qa_plan_group_writes`).
    frozen = _flow_plan(subject, refresh)
    selected_ids = {int(snapshot["plan"]["id"]) for snapshot in frozen}
    project_id = int(subject.get("member_project_id") or subject["project_id"])
    wanted: set[int] = set()
    for snapshot in frozen:
        require_complete_snapshot(snapshot)
    declared = subject["stage"].get("cases")
    if isinstance(declared, Mapping):
        wanted.add(int(declared["plan_id"]))
    for plan_id in sorted(wanted - selected_ids):
        if isinstance(declared, Mapping) and int(declared["plan_id"]) == plan_id:
            incomplete_snapshot(plan_id, "admitted selection has no frozen plan")
        if plan_id in materialized():
            incomplete_snapshot(
                plan_id, "previously materialized selection has no frozen plan"
            )
        frozen.append(
            _plan_snapshot(conn, plan_id, project_id=project_id, lock_plan=lock_plans)
        )
    return frozen
