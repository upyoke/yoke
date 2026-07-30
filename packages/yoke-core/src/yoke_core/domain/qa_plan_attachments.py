"""Plan attachments and case-to-requirement snapshot materialization."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    _placeholder,
    _plan_row,
)
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    require_existing_target,
    require_requirement_id_target,
)
from yoke_core.domain.qa_plan_attachment_validation import (
    require_plan_cases,
    validate_item_transition,
)
from yoke_core.domain.qa_deployment_plan_materialization import (
    materialize_deployment_plan,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from yoke_core.domain.qa_execution_environment_target import (
    resolve_plan_execution_target,
)


def set_project_default(
    conn: Any,
    *,
    plan_id: int,
    workflow_id: str,
    transition_id: str,
    qa_phase: str = "verification",
    actor_id: Optional[int] = None,
) -> dict:
    """Attach one of a transition's project-default plans."""
    plan = _plan_row(conn, plan_id)
    require_plan_cases(conn, plan_id)
    marker = _placeholder(conn)
    if (
        query_one(
            conn,
            f"SELECT 1 FROM workflows WHERE id={marker}",
            (workflow_id,),
        )
        is None
    ):
        raise QaPlanError(f"workflow {workflow_id!r} not found")
    now = iso8601_now()
    conn.execute(
        "INSERT INTO qa_plan_project_defaults("
        "project_id, workflow_id, transition_id, qa_phase, plan_id, "
        "attached_at, attached_by_actor_id"
        f") VALUES ({', '.join([marker] * 7)}) "
        "ON CONFLICT(project_id, workflow_id, transition_id, plan_id) "
        "DO UPDATE SET qa_phase=EXCLUDED.qa_phase, "
        "attached_at=EXCLUDED.attached_at, "
        "attached_by_actor_id=EXCLUDED.attached_by_actor_id",
        (
            int(plan["project_id"]),
            workflow_id,
            transition_id,
            qa_phase,
            plan_id,
            now,
            actor_id,
        ),
    )
    conn.commit()
    return {
        "plan_id": int(plan_id),
        "project_id": int(plan["project_id"]),
        "workflow_id": workflow_id,
        "transition_id": transition_id,
        "qa_phase": qa_phase,
    }


def attach_plan_to_item(
    conn: Any,
    *,
    plan_id: int,
    item_id: int,
    transition_id: str,
    qa_phase: str = "verification",
    actor_id: Optional[int] = None,
    commit: bool = True,
) -> dict:
    """Add an item-specific plan attachment after enforcing project scope."""
    plan = _plan_row(conn, plan_id)
    require_plan_cases(conn, plan_id)
    marker = _placeholder(conn)
    item = query_one(
        conn,
        f"SELECT project_id FROM items WHERE id={marker}",
        (int(item_id),),
    )
    if item is None:
        raise QaPlanError(f"item {item_id} not found")
    if int(item["project_id"]) != int(plan["project_id"]):
        raise QaPlanError("plan and item must belong to the same project")
    lock_item_workflow_bindings(conn, (int(item_id),))
    transition_id = validate_item_transition(
        conn,
        item_id=int(item_id),
        transition_id=transition_id,
    )
    now = iso8601_now()
    try:
        conn.execute(
            "INSERT INTO qa_plan_item_attachments("
            "item_id, transition_id, qa_phase, plan_id, attached_at, "
            "attached_by_actor_id"
            f") VALUES ({', '.join([marker] * 6)}) "
            "ON CONFLICT(item_id, transition_id, plan_id) DO UPDATE SET "
            "qa_phase=EXCLUDED.qa_phase, attached_at=EXCLUDED.attached_at, "
            "attached_by_actor_id=EXCLUDED.attached_by_actor_id",
            (item_id, transition_id, qa_phase, plan_id, now, actor_id),
        )
        if commit:
            conn.commit()
    except Exception:
        if commit:
            conn.rollback()
        raise
    return {
        "plan_id": int(plan_id),
        "item_id": int(item_id),
        "transition_id": transition_id,
        "qa_phase": qa_phase,
    }


def _attached_plans(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
) -> dict[int, dict]:
    marker = _placeholder(conn)
    item = query_one(
        conn,
        f"SELECT project_id, workflow_id FROM items WHERE id={marker}",
        (item_id,),
    )
    if item is None:
        raise QaPlanError(f"item {item_id} not found")
    attachments: dict[int, dict] = {}
    for row in query_rows(
        conn,
        "SELECT plan_id, qa_phase FROM qa_plan_project_defaults "
        f"WHERE project_id={marker} AND workflow_id={marker} "
        f"AND transition_id={marker} ORDER BY plan_id",
        (int(item["project_id"]), str(item["workflow_id"]), transition_id),
    ):
        attachments[int(row["plan_id"])] = dict(row)
    for row in query_rows(
        conn,
        "SELECT plan_id, qa_phase FROM qa_plan_item_attachments "
        f"WHERE item_id={marker} AND transition_id={marker} ORDER BY plan_id",
        (item_id, transition_id),
    ):
        attachments[int(row["plan_id"])] = dict(row)
    return dict(sorted(attachments.items()))


def has_attached_plans(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
) -> bool:
    """Whether materialization has any effective work for this transition."""
    return bool(
        _attached_plans(
            conn,
            item_id=int(item_id),
            transition_id=str(transition_id),
        )
    )


@rollback_workflow_binding_write_errors
def materialize_for_item(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
    commit: bool = True,
) -> dict:
    """Snapshot every attached case into idempotent QA requirements."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    transition_id = validate_item_transition(
        conn,
        item_id=int(item_id),
        transition_id=transition_id,
    )
    attachments = _attached_plans(
        conn,
        item_id=item_id,
        transition_id=transition_id,
    )
    marker = _placeholder(conn)
    created: list[int] = []
    existing: list[int] = []
    now = iso8601_now()
    snapshots: dict[int, tuple[Any, dict, list[Any], list[int], dict]] = {}
    for plan_id, attachment in attachments.items():
        plan = _plan_row(conn, plan_id)
        execution_target = resolve_plan_execution_target(conn, plan_id=plan_id)
        existing_rows = query_rows(
            conn,
            "SELECT id,execution_target_json,execution_target_digest "
            "FROM qa_requirements "
            f"WHERE item_id={marker} AND plan_id={marker} "
            f"AND workflow_transition_id={marker} ORDER BY id",
            (item_id, plan_id, transition_id),
        )
        existing_ids = require_existing_target(
            existing_rows,
            execution_target=execution_target,
            subject=f"item {item_id} transition {transition_id!r}",
        )
        if existing_ids:
            snapshots[plan_id] = (
                plan, attachment, [], existing_ids, execution_target,
            )
            continue
        cases = query_rows(
            conn,
            "SELECT c.*, m.name AS method_name, m.executor_id, "
            "m.required_capability_kind, m.verdict_path "
            "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
            f"WHERE c.plan_id={marker} ORDER BY c.position",
            (plan_id,),
        )
        if not cases:
            raise QaPlanError(
                f"QA plan {plan_id} has no cases and cannot be materialized"
            )
        snapshots[plan_id] = (plan, attachment, cases, [], execution_target)

    for plan_id, (
        plan, attachment, cases, existing_ids, execution_target,
    ) in snapshots.items():
        if existing_ids:
            existing.extend(existing_ids)
            continue
        for case in cases:
            baselines = json.loads(str(case["host_baselines"] or "[]")) or [None]
            for baseline_position, baseline in enumerate(baselines, start=1):
                requirement_id = insert_requirement(
                    conn,
                    item_id=item_id,
                    transition_id=transition_id,
                    plan=plan,
                    attachment=attachment,
                    case=case,
                    baseline=baseline,
                    baseline_position=baseline_position,
                    now=now,
                    execution_target=execution_target,
                )
                if requirement_id is not None:
                    created.append(requirement_id)
                    continue
                requirement_id = existing_requirement_id(
                    conn,
                    item_id=item_id,
                    plan_id=plan_id,
                    case_key=str(case["case_key"]),
                    baseline=baseline,
                    transition_id=transition_id,
                )
                if requirement_id is not None:
                    existing.append(
                        require_requirement_id_target(
                            conn,
                            requirement_id=requirement_id,
                            execution_target=execution_target,
                            subject=(
                                f"item {item_id} transition {transition_id!r}"
                            ),
                        )
                    )
    if commit:
        conn.commit()
    return {
        "item_id": int(item_id),
        "transition_id": transition_id,
        "plan_ids": list(attachments),
        "created_requirement_ids": created,
        "existing_requirement_ids": existing,
    }


def materialize_for_deployment_run(
    conn: Any,
    *,
    deployment_run_id: str,
    plan: str,
    project: Optional[str] = None,
    commit: bool = True,
) -> dict:
    """Snapshot one named project plan onto a real deployment run."""
    return materialize_deployment_plan(
        conn,
        deployment_run_id=deployment_run_id,
        plan=plan,
        project=project,
        commit=commit,
        insert_requirement_fn=insert_requirement,
        existing_requirement_id_fn=existing_requirement_id,
    )


__all__ = [
    "attach_plan_to_item",
    "has_attached_plans",
    "materialize_for_deployment_run",
    "materialize_for_item",
    "set_project_default",
]
