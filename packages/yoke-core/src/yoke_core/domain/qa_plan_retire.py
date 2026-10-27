"""Retire one project QA plan once nothing still depends on it.

A retired plan stays readable as history: its row, cases, requirements and
runs keep their evidence. Retirement only stops the plan answering new work —
editing, materializing and listing by default all skip it. Anything that
would still need the plan refuses retirement by name, with the command that
settles it, so retirement never strands an open obligation.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain.item_terminal_resources import item_is_terminal
from yoke_core.domain.db_helpers import (
    instant_parameter,
    query_one,
    query_rows,
    utc_now,
)
from yoke_core.domain.qa_latest_execution import latest_execution_id_sql
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
from yoke_core.domain.qa_plan_management import QaPlanError, _project_id

DEPENDENTS_CODE = "qa_plan_retire_dependents"


def mark_plan_retired(
    conn: Any, *, plan_id: int, reason: str, actor_id: Optional[int]
) -> None:
    """Write retirement with its reason and actor; the one retired_at writer."""
    now = instant_parameter(conn, utc_now())
    conn.execute(
        "UPDATE qa_plans SET retired_at=%s, updated_at=%s, retirement_reason=%s, "
        "retired_by_actor_id=%s WHERE id=%s AND retired_at IS NULL",
        (now, now, reason, actor_id, int(plan_id)),
    )


def resolve_plan(conn: Any, *, project: str, plan: str) -> dict[str, Any]:
    """Find one plan of the project by slug or numeric id, retired or not."""
    project_id = _project_id(conn, project)
    column = "id" if str(plan).isdecimal() else "slug"
    value: Any = int(plan) if column == "id" else str(plan)
    row = query_one(
        conn,
        "SELECT p.*, pr.slug AS project FROM qa_plans p "
        "JOIN projects pr ON pr.id=p.project_id "
        f"WHERE p.project_id=%s AND p.{column}=%s",
        (project_id, value),
    )
    if row is None:
        raise QaPlanError(
            f"qa_plan_not_found: QA plan {plan!r} not found in project "
            f"{project}; list plans with yoke qa plan list --project {project} "
            "--include-retired"
        )
    return dict(row)


def _open_requirements(conn: Any, plan_id: int) -> list[dict[str, Any]]:
    """Unsettled rows whose newest attempt has not passed.

    Each row says whether it is an item-bound copy on a finished item: no
    future work can need the plan through it, so it never holds retirement.
    """
    rows = [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT q.id, q.item_id, ir.public_ref, q.workflow_transition_id, "
            "q.deployment_run_id, q.deployment_stage, EXISTS(SELECT 1 FROM "
            "qa_runs run WHERE run.qa_requirement_id=q.id) AS has_recorded_run "
            "FROM qa_requirements q "
            "LEFT JOIN item_refs ir ON ir.item_id=COALESCE("
            "q.deployment_member_item_id, q.item_id) "
            f"WHERE q.plan_id=%s AND NOT {settled_obligation_sql(conn, 'q')} "
            "AND NOT EXISTS (SELECT 1 FROM qa_runs r WHERE "
            f"r.id=({latest_execution_id_sql('q.id')}) AND r.verdict='pass') "
            "ORDER BY q.id",
            (int(plan_id),),
        )
    ]
    for row in rows:
        row["finished_item"] = (
            row["item_id"] is not None
            and not row["deployment_run_id"]
            and item_is_terminal(conn, int(row["item_id"])) is True
        )
    return rows


def _settle_finished_item_copies(
    conn: Any, plan_id: int, rows: list[dict[str, Any]], reason: str
) -> list[int]:
    """Retract unexecuted copies left on finished items, keeping executed history.

    A finished item can no longer be claimed, so its holder can never retract
    them through ``qa.item_plan.retract``; retirement provides
    the same retraction once nothing depends on the plan. Executed copies stay as recorded evidence.
    """
    from yoke_core.domain.qa_plan_attachment_retract import (
        retract_plan_from_item,
        retract_requirements,
    )

    unexecuted = [
        row for row in rows if row["finished_item"] and not row["has_recorded_run"]
    ]
    retracted: list[int] = []
    for item_id, transition_id in sorted(
        {(int(row["item_id"]), row["workflow_transition_id"]) for row in unexecuted},
        key=str,
    ):
        attached = query_one(
            conn,
            "SELECT 1 FROM qa_plan_item_attachments WHERE item_id=%s "
            "AND transition_id=%s AND plan_id=%s",
            (item_id, transition_id, int(plan_id)),
        )
        if transition_id is None or attached is None:
            continue
        try:
            retracted += retract_plan_from_item(
                conn,
                item_id=item_id,
                plan_id=int(plan_id),
                transition_id=str(transition_id),
                reason=reason,
                source="operator",
                commit=False,
            )["retired_requirement_ids"]
        except QaPlanError:
            # A sibling copy already ran, so the attachment keeps standing as
            # history; its unexecuted copies still retract one by one below.
            continue
    leftover = sorted({int(row["id"]) for row in unexecuted} - set(retracted))
    retract_requirements(conn, leftover, reason=reason, source="operator")
    return sorted(retracted + leftover)


def _live_executions(conn: Any, plan_id: int, project: str) -> list[str]:
    """Abort recipes for in-flight executions whose roster reaches the plan."""
    rows = query_rows(
        conn,
        "SELECT e.id, e.standalone_plan_id, e.roster_json, e.deployment_run_id, "
        "ir.public_ref FROM qa_plan_executions e "
        "LEFT JOIN item_refs ir ON ir.item_id=e.item_id "
        f"WHERE e.state IN ({LIVE_PLAN_EXECUTION_SQL}) ORDER BY e.created_at",
    )
    live = []
    for row in rows:
        roster = json.loads(row["roster_json"] or "[]")
        if row["standalone_plan_id"] != plan_id and not any(
            isinstance(entry, dict) and entry.get("plan_id") == plan_id
            for entry in roster
        ):
            continue
        if row["deployment_run_id"]:
            subject = f"--deployment-run-id {row['deployment_run_id']}"
        elif row["public_ref"]:
            subject = f"--item {row['public_ref']}"
        else:
            subject = f"--project {project}"
        live.append(
            f"execution {row['id']} is in flight: let it finish, or yoke qa "
            f"plan abort {subject} --execution-id {row['id']} --reason R"
        )
    return live


def _project_defaults(conn: Any, plan_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT workflow_id, transition_id FROM qa_plan_project_defaults "
            "WHERE plan_id=%s ORDER BY workflow_id, transition_id",
            (int(plan_id),),
        )
    ]


def _requirement_line(project: str, plan_id: int, row: dict[str, Any]) -> str:
    if row["deployment_run_id"]:
        subject = f"run {row['deployment_run_id']} stage {row['deployment_stage']}"
        if row["public_ref"]:
            subject += f" member {row['public_ref']}"
        settle = (
            f"yoke qa requirement waive --requirement-id {row['id']} "
            "--rationale R, or yoke qa requirement supersede --help"
        )
    else:
        subject = f"item {row['public_ref']}"
        settle = (
            f"yoke qa item-plan retract --item {row['public_ref']} --project "
            f"{project} --plan-id {plan_id} --transition "
            f"{row['workflow_transition_id']} --reason R (unexecuted), or yoke qa "
            f"requirement waive --requirement-id {row['id']} --rationale R"
        )
    return f"requirement {row['id']} ({subject}): {settle}"


def retirement_dependents(conn: Any, plan: dict[str, Any]) -> list[str]:
    """Name everything that still needs the plan, each with its recovery."""
    plan_id, project = int(plan["id"]), str(plan["project"])
    lines = [
        _requirement_line(project, plan_id, row)
        for row in _open_requirements(conn, plan_id)
        if not row["finished_item"]
    ]
    lines += _live_executions(conn, plan_id, project)
    lines += [
        f"project default {row['workflow_id']}/{row['transition_id']}: yoke qa "
        f"project-default unset --project {project} --plan-id {plan_id} "
        f"--workflow {row['workflow_id']} --transition {row['transition_id']}"
        for row in _project_defaults(conn, plan_id)
    ]
    return lines


def _retirement(
    plan: dict[str, Any],
    *,
    already_retired: bool,
    retracted_requirement_ids: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "plan_id": int(plan["id"]),
        "project": str(plan["project"]),
        "slug": str(plan["slug"]),
        "retired_at": plan["retired_at"],
        "retirement_reason": plan.get("retirement_reason"),
        "retired_by_actor_id": plan.get("retired_by_actor_id"),
        "already_retired": already_retired,
        "retracted_requirement_ids": retracted_requirement_ids or [],
    }


def retire_plan(
    conn: Any,
    *,
    project: str,
    plan: str,
    reason: str,
    actor_id: Optional[int],
) -> dict[str, Any]:
    """Retire the plan, or refuse naming every dependent and its recovery.

    Unexecuted copies left on finished items retract in the same
    transaction and are returned by id. Repeating the call on a retired plan
    answers with the recorded retirement unchanged, so a retry after a lost
    reply is safe.
    """
    text = str(reason or "").strip()
    if not text:
        raise QaPlanError(
            "qa_plan_retire_reason_required: say why the plan is retired with "
            "--reason; the reason is the plan's durable retirement record"
        )
    row = resolve_plan(conn, project=project, plan=plan)
    if row["retired_at"] is not None:
        return _retirement(row, already_retired=True)
    dependents = retirement_dependents(conn, row)
    if dependents:
        raise QaPlanError(
            f"{DEPENDENTS_CODE}: QA plan {row['project']}/{row['slug']} "
            f"(id {row['id']}) still has {len(dependents)} dependent(s). "
            "Settle each, then retry the retirement:\n- " + "\n- ".join(dependents)
        )
    retracted = _settle_finished_item_copies(
        conn,
        int(row["id"]),
        _open_requirements(conn, int(row["id"])),
        f"QA plan retired: {text}",
    )
    mark_plan_retired(conn, plan_id=int(row["id"]), reason=text, actor_id=actor_id)
    conn.commit()
    return _retirement(
        resolve_plan(conn, project=project, plan=str(row["id"])),
        already_retired=False,
        retracted_requirement_ids=retracted,
    )


__all__ = [
    "DEPENDENTS_CODE",
    "mark_plan_retired",
    "resolve_plan",
    "retire_plan",
    "retirement_dependents",
]
