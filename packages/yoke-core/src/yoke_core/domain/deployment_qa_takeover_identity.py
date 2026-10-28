"""Continuation authority for QA admitted before an authorized release takeover."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.deployment_qa_presentation_reads import presentation_read


def inherited_target(conn: Any, run_id: str, target: Mapping) -> bool:
    """Prove the immutable starting release is an ancestor on the same target."""
    original = str((target.get("deployment") or {}).get("run_id") or "")
    if not original or original == str(run_id):
        return False

    def read():
        return (
            query_one(
                conn,
                "WITH RECURSIVE owners AS ("
                "SELECT id,supersedes_run_id,project_id,flow,target_environment_id "
                "FROM deployment_runs WHERE id=%s UNION "
                "SELECT p.id,p.supersedes_run_id,p.project_id,p.flow,p.target_environment_id "
                "FROM deployment_runs p JOIN owners c ON p.id=c.supersedes_run_id "
                "AND p.project_id=c.project_id AND p.flow=c.flow "
                "AND p.target_environment_id IS NOT DISTINCT FROM c.target_environment_id) "
                "SELECT id FROM owners WHERE id=%s",
                (str(run_id), original),
            )
            is not None
        )

    return presentation_read(
        conn, ("qa_takeover_ancestor", str(run_id), original), read
    )


def continued_subject(conn: Any, execution: Mapping, target: Mapping) -> dict | None:
    """Resolve moved work without demanding successor deployment acceptance.

    Original admission supplies frozen QA policy. Current membership, project,
    tenant and takeover links supply authority; a release approval is never copied.
    """
    run_id = str(execution["deployment_run_id"])
    if not inherited_target(conn, run_id, target):
        return None
    from yoke_core.domain.deployment_qa_stage_contract import _read_run, _run_stage
    from yoke_core.domain.qa_execution_environment_target import target_digest

    identity = target["deployment"]
    stage_name = str(execution["deployment_stage"])
    admitted = _run_stage(conn, str(identity["run_id"]), stage_name)
    current = _read_run(conn, run_id)
    if current is None or current["status"] == "cancelled":
        raise ValueError(
            "qa_execution_owner_cancelled: the owning release was cancelled; "
            "inspect the execution and finish its recorded abort or cleanup"
        )
    if stage_name != identity.get("stage") or int(current["tenant_id"]) != int(
        (target.get("tenant") or {}).get("id") or 0
    ):
        raise ValueError(
            "qa_execution_scope_mismatch: preserved QA does not match its stage or tenant; "
            "inspect the execution's original target before retrying"
        )
    member = execution.get("deployment_member_item_id")
    if member != identity.get("member_item_id"):
        raise ValueError(
            "qa_execution_member_mismatch: preserved QA belongs to another member; "
            "use the execution owned by the intended item"
        )
    if (
        query_one(
            conn,
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_stage=%s AND deployment_member_item_id IS NOT DISTINCT FROM %s "
            "AND execution_target_digest=%s LIMIT 1",
            (run_id, stage_name, member, target_digest(target)),
        )
        is None
    ):
        raise ValueError(
            "qa_execution_target_unowned: the current release has no obligation for "
            "this exact frozen target; inspect the execution's recorded target"
        )
    members = [int(member)] if member is not None else []
    rows = (
        query_rows(
            conn,
            "SELECT m.item_id,m.requirement_snapshot,i.project_id FROM deployment_run_items m "
            "JOIN items i ON i.id=m.item_id WHERE m.run_id=%s AND m.item_id=ANY(%s)",
            (run_id, members),
        )
        if members
        else []
    )
    project_id = int((target.get("project") or {}).get("id") or 0)
    rows = [row for row in rows if int(row["project_id"]) == project_id]
    expected_scope = "item" if member is not None else "run"
    if admitted["stage"].get("scope") != expected_scope or (
        not rows
        if expected_scope == "item"
        else project_id != int(current["project_id"])
    ):
        raise ValueError(
            "qa_execution_subject_detached: no authorized member or project owns this QA; "
            "inspect current release membership and the execution's abort state"
        )
    snapshot = rows[0]["requirement_snapshot"] if rows else None
    if snapshot and not isinstance(snapshot, Mapping):
        snapshot = json.loads(str(snapshot))
    subject = {
        **current,
        "stage": admitted["stage"],
        "stages": admitted["stages"],
        "flow_snapshot": admitted["flow_snapshot"],
        "member_item_id": member,
        "member_project_id": project_id if rows else None,
        "member_snapshot": snapshot if member is not None else None,
    }
    return subject


def _continued_group_subject(conn, run_id, stage, target, group) -> dict:
    """A moved group continues under its original stage policy and the current run.

    Like :func:`continued_subject`, the successor need not have reached or
    accepted the stage for a walk takeover moved to keep running.
    """
    from yoke_core.domain.deployment_qa_plan_group_writes import group_subject_from
    from yoke_core.domain.deployment_qa_stage_contract import _read_run, _run_stage

    admitted = _run_stage(conn, str(target["deployment"]["run_id"]), stage)
    current = _read_run(conn, run_id)
    if current is None or current["status"] == "cancelled":
        raise ValueError(
            "qa_execution_owner_cancelled: the owning release was cancelled; "
            "inspect the execution and finish its recorded abort or cleanup"
        )
    run = {
        **current,
        "stage": admitted["stage"],
        "stages": admitted["stages"],
        "flow_snapshot": admitted["flow_snapshot"],
    }
    return group_subject_from(run, group)


def read_execution_subject(
    conn: Any, execution: Mapping, target: Mapping, *, require_active: bool
) -> dict:
    run_id = str(execution["deployment_run_id"])
    stage = str(execution["deployment_stage"])
    if (target.get("deployment") or {}).get("shared_plan"):
        # A plan group is found by its own group_id, wherever takeover moved it.
        from yoke_core.domain.deployment_qa_plan_group_writes import group_subject
        from yoke_core.domain.deployment_qa_plan_groups import group_for_target

        group = group_for_target(conn, run_id, target)
        if group is None:
            raise ValueError(
                f"plan_group_missing: run {run_id!r} holds no plan group for this "
                "execution's target; read `yoke deployment-runs get "
                f"{run_id}` and run the plan's current group"
            )
        if inherited_target(conn, run_id, target):
            return _continued_group_subject(conn, run_id, stage, target, group)
        return group_subject(conn, run_id, stage, group, require_active=require_active)
    continued = continued_subject(conn, execution, target)
    if continued is not None:
        return continued
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )

    return deployment_qa_stage_subject(
        conn,
        run_id=str(execution["deployment_run_id"]),
        stage_name=str(execution["deployment_stage"]),
        member_item_id=execution.get("deployment_member_item_id"),
        require_active=require_active,
    )

