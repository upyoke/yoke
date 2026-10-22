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
    from yoke_core.domain.deployment_qa_shared_plan_reads import attaching_members
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
    shared = identity.get("shared_plan")
    member = execution.get("deployment_member_item_id")
    if member != identity.get("member_item_id") or (shared and member is not None):
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
    members = (
        attaching_members(conn, run_id, int(shared["plan_id"]))
        if shared
        else [int(member)]
        if member is not None
        else []
    )
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
    expected_scope = "item" if member is not None or shared else "run"
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
    if shared:
        subject.update(shared_plan=shared, shared_target=dict(target))
    return subject


def read_execution_subject(
    conn: Any, execution: Mapping, target: Mapping, *, require_active: bool
) -> dict:
    continued = continued_subject(conn, execution, target)
    if continued is not None:
        return continued
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )

    from yoke_core.domain.deployment_qa_shared_plans import resolve_shared_subject

    shared = (target.get("deployment") or {}).get("shared_plan")
    if shared:
        return resolve_shared_subject(
            conn,
            run_id=str(execution["deployment_run_id"]),
            stage_name=str(execution["deployment_stage"]),
            plan_id=int(shared["plan_id"]),
            expected_target=target,
            require_active=require_active,
        )
    return deployment_qa_stage_subject(
        conn,
        run_id=str(execution["deployment_run_id"]),
        stage_name=str(execution["deployment_stage"]),
        member_item_id=execution.get("deployment_member_item_id"),
        require_active=require_active,
    )
