"""Select one host roster without losing a deployment member's obligations."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.machine_qa_case_machine import (
    resolve_case_machine,
)
from yoke_core.domain.machine_qa_case_hosts import case_machines
from yoke_core.domain.qa_plan_run_target_partition import (
    run_target_partition,
    target_passed_requirements,
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
    """Use scoped evidence to advance between serial host executions.

    A live roster stays immutable through capture and review. A completed
    execution covers its own requirements whose current scoped verdict and
    artifacts still pass the stage's existing evidence checks; a current pass
    on this target covers its requirement whichever execution recorded it,
    including an aborted one. A single-host deployment roster drops those
    passes through :func:`run_target_partition`.
    """

    from yoke_core.domain.qa_plan_chain_hosts import chain_host_groups

    groups = chain_host_groups(roster)

    def host_group(row):
        return groups[int(row["requirement_id"])]

    scope = dict(
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    host_sets = {
        host_group(row) for row in roster if case_machines(row) or host_group(row)[2]
    }
    if (
        not deployment_stage
        or (
            deployment_member_item_id is None
            and not (
                (roster[0].get("execution_target") or {}).get("deployment") or {}
            ).get("shared_plan")
            and not any(isolated for _driver, _hosts, isolated in host_sets)
        )
        or (
            len(host_sets) < 2
            and not any(isolated for _driver, _hosts, isolated in host_sets)
            and not any(len(hosts) > 1 for _driver, hosts, _isolated in host_sets)
        )
    ):
        if not deployment_stage:
            return roster, None, None
        return run_target_partition(conn, roster, **scope), None, None
    for row in roster:
        resolve_case_machine(row, machine)
    from yoke_core.domain.deployment_qa_stage_case_failures import case_failures

    digest = str(roster[0]["execution_target_digest"])
    shared = ((roster[0].get("execution_target") or {}).get("deployment") or {}).get(
        "shared_plan"
    ) or {}
    failures = case_failures(
        conn,
        run_id=str(deployment_run_id),
        stage_name=deployment_stage,
        member_item_id=deployment_member_item_id,
        execution_target_digest=digest,
        shared_plan_id=shared.get("plan_id"),
    )
    unresolved = {failure.requirement_id for failure in failures}
    p = marker(conn)
    history = conn.execute(
        "SELECT id,roster_json FROM qa_plan_executions "
        f"WHERE deployment_run_id={p} AND deployment_stage={p} "
        f"AND COALESCE(deployment_member_item_id,0)={p} AND execution_target_digest={p} "
        "AND state='completed' ORDER BY execution_order DESC",
        (deployment_run_id, deployment_stage, deployment_member_item_id or 0, digest),
    ).fetchall()
    covered = {
        int(case["requirement_id"])
        for row in history
        for case in json.loads(
            str(row["roster_json"] if hasattr(row, "keys") else row[1])
        )
    } - unresolved
    covered |= target_passed_requirements(conn, roster, **scope)
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

    if not pending and history:
        row = history[0]
        execution_id = str(row["id"] if hasattr(row, "keys") else row[0])
        return [], 0, select_plan_execution(conn, execution_id, lock=False)
    pending = pending or roster
    selected_hosts = next(
        (
            host_group(row)
            for row in pending
            if case_machines(row) or host_group(row)[2]
        ),
        (None, (), None),
    )
    selected = [
        {**row, "ordinal": ordinal}
        for ordinal, row in enumerate(
            row
            for row in pending
            if host_group(row) == selected_hosts
            or (selected_hosts[2] is None and host_group(row) == (None, (), None))
        )
    ]
    return selected, len(pending) - len(selected), None
