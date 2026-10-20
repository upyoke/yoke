"""Recover host identity from durable QA execution and run evidence."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.machine_config.test_machine import (
    validate_test_machine_resource_name,
)
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.qa_plan_execution_store import marker


def run_machine(conn: Any, raw: str) -> str | None:
    try:
        document = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    machine = (document.get("evidence") or {}).get("machine")
    if machine:
        return validate_test_machine_resource_name(machine)
    lease = (document.get("host_control_submission") or {}).get("lease_id")
    return get_claim(conn, int(lease)).target.machine_id if lease else None


def execution_machine(
    conn: Any, execution: Mapping[str, Any], case: Mapping[str, Any]
) -> str | None:
    """Recover a single-host case's platform host from custody and run history."""
    from yoke_core.domain.machine_qa_case_hosts import case_machines

    if len(case_machines(case)) > 1:
        return None

    from yoke_core.domain.machine_qa_case_platform import case_platform
    from yoke_core.domain.machine_qa_capability_rows import test_machine_capability_rows
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    platform = case_platform(case)
    hosts = {
        row.machine: row.settings["os"]
        for row in test_machine_capability_rows(
            conn, project_id=int(case["project_id"])
        )
    }

    def matches(machine: str | None) -> bool:
        if machine and platform is not None and machine not in hosts:
            raise ValueError(
                f"qa_resume_host_unregistered: recorded host {machine!r} is no longer "
                "registered for this project; restore its Test Machine registration "
                "before resuming so its preserved state is not lost"
            )
        return bool(machine) and (platform is None or hosts.get(machine) == platform)

    if case.get("requirement_id"):
        corrected = corrected_case_machine(conn, int(case["requirement_id"]))
        if corrected and matches(corrected):
            return corrected
    p = marker(conn)
    seen = set()
    while str(execution["id"]) not in seen:
        seen.add(str(execution["id"]))
        if execution.get("machine_lease_id"):
            machine = get_claim(
                conn, int(execution["machine_lease_id"])
            ).target.machine_id
            if matches(machine):
                return machine
        results = conn.execute(
            f"SELECT result_json FROM qa_plan_execution_results WHERE execution_id={p} "
            "ORDER BY ordinal DESC",
            (str(execution["id"]),),
        ).fetchall()
        run_ids = [
            result["run_id"]
            for row in results
            if (result := json.loads(row["result_json"])).get("run_id")
        ]
        if run_ids:
            runs = conn.execute(
                f"SELECT id,raw_result FROM qa_runs WHERE id IN ({', '.join([p] * len(run_ids))})",
                tuple(int(run_id) for run_id in run_ids),
            ).fetchall()
            by_id = {int(run["id"]): run["raw_result"] for run in runs}
            for run_id in run_ids:
                if run_id in by_id:
                    machine = run_machine(conn, by_id[run_id])
                    if matches(machine):
                        return machine
        source = execution.get("continues_execution_id")
        if not source:
            return None
        execution = select_plan_execution(conn, str(source), lock=False)
    raise ValueError(
        "qa_resume_history_cycle: execution continuation history repeats; "
        "ask the control-plane operator to repair its source links before resuming"
    )


def corrected_case_machine(conn: Any, requirement_id: int) -> str | None:
    """Follow a corrected case's durable predecessor links to its attempted host."""
    p = marker(conn)
    seen = set()
    pending = [requirement_id]
    machines = set()
    while pending:
        current = pending.pop()
        if current in seen:
            raise ValueError(
                "qa_resume_correction_cycle: corrected requirement history repeats; "
                "ask the control-plane operator to repair its successor links"
            )
        seen.add(current)
        predecessors = conn.execute(
            f"SELECT id FROM qa_requirements WHERE replacement_requirement_id={p} "
            f"OR superseded_by_requirement_id={p} ORDER BY id",
            (current, current),
        ).fetchall()
        for predecessor in predecessors:
            prior = int(predecessor["id"])
            row = conn.execute(
                f"SELECT raw_result FROM qa_runs WHERE qa_requirement_id={p} "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (prior,),
            ).fetchone()
            if row and (machine := run_machine(conn, row["raw_result"])):
                machines.add(machine)
            else:
                pending.append(prior)
        if len(machines) > 1:
            raise ValueError(
                "qa_resume_correction_hosts_conflict: this corrected case replaces "
                "attempts on different hosts; split the correction into one case "
                "per original host before resuming"
            )
    return next(iter(machines), None)
