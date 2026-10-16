"""Resolve unretracted frozen requirements and plans for a deployment QA stage."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql
from yoke_core.domain.qa_plan_attachment_reads import retracted_item_plan_ids
from yoke_core.domain.qa_deployment_member_attached_plans import (
    attached_member_plan_ids,
    stage_environment_id_for_plan_selection,
)


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
    """Read frozen content, while honoring later source/attachment withdrawals."""
    snapshot = subject.get("member_snapshot")
    if not isinstance(snapshot, Mapping):
        return []
    requirements = [
        dict(requirement)
        for requirement in snapshot.get("requirements") or []
        if isinstance(requirement, Mapping) and requirement_applies(requirement, target)
    ]
    if not requirements:
        return []
    withdrawn_plans = retracted_item_plan_ids(conn, int(subject["member_item_id"]))
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
        and requirement.get("plan_id") not in withdrawn_plans
    ]


def _flow_plan(subject: Mapping[str, Any]) -> list[dict[str, Any]]:
    stage = str(subject["stage"]["name"])
    return [
        dict(selection)
        for selection in subject["flow_snapshot"].get("selections") or []
        if isinstance(selection, Mapping) and str(selection.get("stage") or "") == stage
    ]


def _member_plans(
    conn: Any,
    subject: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
) -> list[dict[str, Any]]:
    snapshot = subject.get("member_snapshot")
    if not isinstance(snapshot, Mapping):
        return []
    stage_environment_id = stage_environment_id_for_plan_selection(conn, target)
    withdrawn_plans = retracted_item_plan_ids(conn, int(subject["member_item_id"]))
    selected: list[dict[str, Any]] = []
    for value in snapshot.get("plans") or []:
        if not isinstance(value, Mapping):
            continue
        # A correction keeps its complete contract, but answers the original
        # group rather than selecting an additional standalone obligation.
        if value.get("replacement_scopes"):
            continue
        from yoke_core.domain.deployment_qa_snapshot_selection import (
            require_complete_snapshot,
        )

        attachment = value.get("attachment")
        plan = value.get("plan")
        if not isinstance(attachment, Mapping) or not isinstance(plan, Mapping):
            continue
        if str(attachment.get("qa_phase") or "") != "post_deploy":
            continue
        if int(plan["id"]) in withdrawn_plans:
            continue
        require_complete_snapshot(value)
        from yoke_core.domain.qa_plan_case_targets import (
            case_applies_to_target,
            case_target_envs,
        )

        from yoke_core.domain.deployment_qa_snapshot_selection import (
            plan_matches_target,
        )

        default_matches = plan_matches_target(conn, plan, target, stage_environment_id)
        cases = [
            case
            for case in value.get("cases", ())
            if case_applies_to_target(case, target)
            and (case_target_envs(case) or default_matches)
        ]
        if cases:
            selected.append({**dict(value), "cases": cases})
    return selected


def frozen_stage_plans(
    conn: Any,
    subject: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    admitted: list[dict[str, Any]],
    lock_plans: bool = True,
) -> list[dict[str, Any]]:
    """Keep plan-owned obligations on their plan's ordered snapshot path."""
    frozen = [*_flow_plan(subject), *_member_plans(conn, subject, target=target)]
    selected_ids = {int(snapshot["plan"]["id"]) for snapshot in frozen}
    project_id = int(subject.get("member_project_id") or subject["project_id"])
    wanted = {int(r["plan_id"]) for r in admitted if r.get("plan_id") is not None}
    if subject.get("member_item_id") is not None:
        wanted.update(
            attached_member_plan_ids(
                conn,
                member_item_id=int(subject["member_item_id"]),
                environment_id=stage_environment_id_for_plan_selection(conn, target),
            )
        )
    from yoke_core.domain.deployment_qa_snapshot_selection import (
        incomplete_snapshot,
        materialized_plan_ids,
        require_complete_snapshot,
    )

    for snapshot in frozen:
        require_complete_snapshot(snapshot)
    declared = subject["stage"].get("cases")
    if isinstance(declared, Mapping):
        wanted.add(int(declared["plan_id"]))
    historical = None
    for plan_id in sorted(wanted - selected_ids):
        if any(r.get("plan_id") == plan_id for r in admitted) or (
            isinstance(declared, Mapping) and int(declared["plan_id"]) == plan_id
        ):
            incomplete_snapshot(plan_id, "admitted selection has no frozen plan")
        if historical is None:
            historical = materialized_plan_ids(conn, subject)
        if plan_id in historical:
            incomplete_snapshot(
                plan_id, "previously materialized selection has no frozen plan"
            )
        frozen.append(
            _plan_snapshot(conn, plan_id, project_id=project_id, lock_plan=lock_plans)
        )
    return frozen
