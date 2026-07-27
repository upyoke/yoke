"""Plan attachments and case-to-requirement snapshot materialization."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    _json,
    _placeholder,
    _plan_row,
)


def _require_plan_cases(conn: Any, plan_id: int) -> None:
    marker = _placeholder(conn)
    row = query_one(
        conn,
        f"SELECT 1 FROM qa_plan_cases WHERE plan_id={marker} LIMIT 1",
        (int(plan_id),),
    )
    if row is None:
        raise QaPlanError(
            f"QA plan {plan_id} has no cases and cannot be attached or "
            "materialized"
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
    _require_plan_cases(conn, plan_id)
    marker = _placeholder(conn)
    if query_one(
        conn, f"SELECT 1 FROM workflows WHERE id={marker}", (workflow_id,),
    ) is None:
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
            int(plan["project_id"]), workflow_id, transition_id, qa_phase,
            plan_id, now, actor_id,
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
    _require_plan_cases(conn, plan_id)
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
    now = iso8601_now()
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
    return {
        "plan_id": int(plan_id),
        "item_id": int(item_id),
        "transition_id": transition_id,
        "qa_phase": qa_phase,
    }


def _attached_plans(
    conn: Any, *, item_id: int, transition_id: str,
) -> dict[int, dict]:
    marker = _placeholder(conn)
    item = query_one(
        conn,
        "SELECT project_id, workflow_id FROM items "
        f"WHERE id={marker}",
        (item_id,),
    )
    if item is None:
        raise QaPlanError(f"item {item_id} not found")
    attachments: dict[int, dict] = {}
    for row in query_rows(
        conn,
        "SELECT plan_id, qa_phase FROM qa_plan_project_defaults "
        f"WHERE project_id={marker} AND workflow_id={marker} "
        f"AND transition_id={marker}",
        (int(item["project_id"]), str(item["workflow_id"]), transition_id),
    ):
        attachments[int(row["plan_id"])] = dict(row)
    for row in query_rows(
        conn,
        "SELECT plan_id, qa_phase FROM qa_plan_item_attachments "
        f"WHERE item_id={marker} AND transition_id={marker}",
        (item_id, transition_id),
    ):
        attachments[int(row["plan_id"])] = dict(row)
    return attachments


def _insert_requirement(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
    plan: Any,
    attachment: dict,
    case: Any,
    baseline: Optional[str],
    now: str,
) -> Optional[int]:
    marker = _placeholder(conn)
    policy_id = case["success_policy_id"] or plan["success_policy_id"]
    params = (
        json.loads(str(case["success_policy_params"]))
        if case["success_policy_params"] is not None
        else json.loads(str(plan["success_policy_params"]))
    )
    row = conn.execute(
        "INSERT INTO qa_requirements("
        "item_id, qa_kind, qa_phase, blocking_mode, "
        "requirement_source, success_policy, capability_requirements, "
        "plan_id, plan_case_key, method_id, host_baseline, "
        "workflow_transition_id, instructions, expected_outcome, "
        "method_config, created_at"
        f") VALUES ({', '.join([marker] * 16)}) "
        "ON CONFLICT DO NOTHING RETURNING id",
        (
            item_id,
            "plan_case",
            str(attachment["qa_phase"]),
            "blocking",
            "flow_derived",
            _json({"id": policy_id, "params": params}),
            _json([case["required_capability_kind"]])
            if case["required_capability_kind"] else _json([]),
            int(plan["id"]),
            str(case["case_key"]),
            str(case["method_id"]),
            baseline,
            transition_id,
            str(case["instructions"]),
            str(case["expected_outcome"]),
            str(case["method_config"]),
            now,
        ),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"] if isinstance(row, dict) else row[0])


def _existing_requirement_id(
    conn: Any,
    *,
    item_id: int,
    plan_id: int,
    case_key: str,
    baseline: Optional[str],
    transition_id: str,
) -> Optional[int]:
    marker = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT id FROM qa_requirements "
        f"WHERE item_id={marker} AND plan_id={marker} "
        f"AND plan_case_key={marker} "
        f"AND COALESCE(host_baseline, '')={marker} "
        f"AND workflow_transition_id={marker}",
        (item_id, plan_id, case_key, baseline or "", transition_id),
    )
    return int(row["id"]) if row is not None else None


def materialize_for_item(
    conn: Any, *, item_id: int, transition_id: str,
) -> dict:
    """Snapshot every attached case into idempotent QA requirements."""
    attachments = _attached_plans(
        conn, item_id=item_id, transition_id=transition_id,
    )
    marker = _placeholder(conn)
    created: list[int] = []
    existing: list[int] = []
    now = iso8601_now()
    snapshots: dict[int, tuple[Any, dict, list[Any], list[int]]] = {}
    for plan_id, attachment in attachments.items():
        plan = _plan_row(conn, plan_id)
        existing_rows = query_rows(
            conn,
            "SELECT id FROM qa_requirements "
            f"WHERE item_id={marker} AND plan_id={marker} "
            f"AND workflow_transition_id={marker} ORDER BY id",
            (item_id, plan_id, transition_id),
        )
        existing_ids = [int(row["id"]) for row in existing_rows]
        if existing_ids:
            snapshots[plan_id] = (plan, attachment, [], existing_ids)
            continue
        cases = query_rows(
            conn,
            "SELECT c.*, m.required_capability_kind "
            "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
            f"WHERE c.plan_id={marker} ORDER BY c.position",
            (plan_id,),
        )
        if not cases:
            raise QaPlanError(
                f"QA plan {plan_id} has no cases and cannot be materialized"
            )
        snapshots[plan_id] = (plan, attachment, cases, [])

    for plan_id, (plan, attachment, cases, existing_ids) in snapshots.items():
        if existing_ids:
            existing.extend(existing_ids)
            continue
        for case in cases:
            baselines = json.loads(str(case["host_baselines"] or "[]")) or [None]
            for baseline in baselines:
                requirement_id = _insert_requirement(
                    conn,
                    item_id=item_id,
                    transition_id=transition_id,
                    plan=plan,
                    attachment=attachment,
                    case=case,
                    baseline=baseline,
                    now=now,
                )
                if requirement_id is not None:
                    created.append(requirement_id)
                    continue
                requirement_id = _existing_requirement_id(
                    conn,
                    item_id=item_id,
                    plan_id=plan_id,
                    case_key=str(case["case_key"]),
                    baseline=baseline,
                    transition_id=transition_id,
                )
                if requirement_id is not None:
                    existing.append(requirement_id)
    conn.commit()
    return {
        "item_id": int(item_id),
        "transition_id": transition_id,
        "plan_ids": list(attachments),
        "created_requirement_ids": created,
        "existing_requirement_ids": existing,
    }


__all__ = [
    "attach_plan_to_item",
    "materialize_for_item",
    "set_project_default",
]
