"""Select one host roster without losing a deployment member's obligations."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.machine_qa_case_machine import (
    required_case_machine,
    resolve_case_machine,
)
from yoke_core.domain.qa_plan_execution_store import (
    live_plan_execution_id,
    marker,
    select_plan_execution,
)


def member_machine_partition(
    conn: Any,
    roster: list[dict[str, Any]],
    *,
    deployment_run_id: str | None,
    deployment_stage: str | None,
    deployment_member_item_id: int | None,
    machine: str | None,
) -> tuple[list[dict[str, Any]], int | None, dict[str, Any] | None]:
    """Use completed scoped evidence to advance between serial host executions.

    A live roster stays immutable through capture and review. A completed
    execution covers only its own requirements whose current scoped verdict
    and artifacts still pass the stage's existing evidence checks.
    """
    machines = {
        required_case_machine(row.get("required_capability_kinds")) for row in roster
    }
    machines.discard(None)
    if not deployment_stage or deployment_member_item_id is None or len(machines) < 2:
        return roster, None, None
    for row in roster:
        resolve_case_machine(row, machine)
    scope = dict(
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    from yoke_core.domain.deployment_qa_stage_case_failures import case_failures

    digest = str(roster[0]["execution_target_digest"])
    failures = case_failures(
        conn,
        run_id=str(deployment_run_id),
        stage_name=deployment_stage,
        member_item_id=deployment_member_item_id,
        execution_target_digest=digest,
    )
    unresolved = {failure.requirement_id for failure in failures}
    p = marker(conn)
    history = conn.execute(
        "SELECT id,roster_json FROM qa_plan_executions "
        f"WHERE deployment_run_id={p} AND deployment_stage={p} "
        f"AND deployment_member_item_id={p} AND execution_target_digest={p} "
        "AND state='completed' ORDER BY execution_order DESC",
        (deployment_run_id, deployment_stage, deployment_member_item_id, digest),
    ).fetchall()
    covered = {
        int(case["requirement_id"])
        for row in history
        for case in json.loads(
            str(row["roster_json"] if hasattr(row, "keys") else row[1])
        )
    } - unresolved
    pending = [row for row in roster if int(row["requirement_id"]) not in covered]
    live_id = live_plan_execution_id(conn, **scope)
    if live_id:
        live = select_plan_execution(conn, live_id, lock=False)
        ids = {int(row["requirement_id"]) for row in live["roster"]}
        selected = [
            {**row, "ordinal": ordinal}
            for ordinal, row in enumerate(
                row for row in roster if int(row["requirement_id"]) in ids
            )
        ]
        return (
            selected,
            sum(int(row["requirement_id"]) not in ids for row in pending),
            None,
        )

    if not pending:
        row = history[0]
        execution_id = str(row["id"] if hasattr(row, "keys") else row[0])
        return [], 0, select_plan_execution(conn, execution_id, lock=False)
    selected_machine = next(
        (
            name
            for row in pending
            if (name := required_case_machine(row.get("required_capability_kinds")))
        ),
        None,
    )
    selected = [
        {**row, "ordinal": ordinal}
        for ordinal, row in enumerate(
            row
            for row in pending
            if required_case_machine(row.get("required_capability_kinds"))
            in {None, selected_machine}
        )
    ]
    return selected, len(pending) - len(selected), None
