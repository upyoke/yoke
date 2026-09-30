"""Resolve frozen and requirement-owned plans for a deployment QA stage."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
from yoke_core.domain.qa_deployment_member_attached_plans import (
    attached_member_plans,
    plan_matches_stage_environment,
    stage_environment_id_for_plan_selection,
)


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
    selected: list[dict[str, Any]] = []
    for value in snapshot.get("plans") or []:
        if not isinstance(value, Mapping):
            continue
        attachment = value.get("attachment")
        plan = value.get("plan")
        if not isinstance(attachment, Mapping) or not isinstance(plan, Mapping):
            continue
        if str(attachment.get("qa_phase") or "") != "post_deploy":
            continue
        if not plan_matches_stage_environment(
            plan.get("target_environment_id"), stage_environment_id
        ):
            continue
        selected.append(dict(value))
    return selected


def frozen_stage_plans(
    conn: Any,
    subject: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    admitted: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep plan-owned obligations on their plan's ordered snapshot path."""
    frozen = [*_flow_plan(subject), *_member_plans(conn, subject, target=target)]
    if not frozen:
        frozen = attached_member_plans(conn, subject, target=target)
    selected_ids = {int(snapshot["plan"]["id"]) for snapshot in frozen}
    project_id = int(subject.get("member_project_id") or subject["project_id"])
    for requirement in admitted:
        plan_id = requirement.get("plan_id")
        if plan_id is None or int(plan_id) in selected_ids:
            continue
        frozen.append(_plan_snapshot(conn, int(plan_id), project_id=project_id))
        selected_ids.add(int(plan_id))
    return frozen
