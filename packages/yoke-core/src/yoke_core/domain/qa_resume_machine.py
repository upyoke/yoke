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


def execution_machine(conn: Any, execution: Mapping[str, Any]) -> str | None:
    if execution.get("machine_lease_id"):
        return get_claim(conn, int(execution["machine_lease_id"])).target.machine_id
    p = marker(conn)
    rows = conn.execute(
        f"SELECT result_json FROM qa_plan_execution_results WHERE execution_id={p} "
        "ORDER BY ordinal DESC",
        (str(execution["id"]),),
    ).fetchall()
    run_ids = [
        result["run_id"]
        for row in rows
        if (result := json.loads(row["result_json"])).get("run_id")
    ]
    if not run_ids:
        return None
    runs = conn.execute(
        f"SELECT id,raw_result FROM qa_runs WHERE id IN ({', '.join([p] * len(run_ids))})",
        tuple(int(run_id) for run_id in run_ids),
    ).fetchall()
    by_id = {int(run["id"]): run["raw_result"] for run in runs}
    for run_id in run_ids:
        if run_id in by_id and (machine := run_machine(conn, by_id[run_id])):
            return machine
    return None


def correction_machine(conn: Any, replacements: Any) -> str | None:
    machines = set()
    p = marker(conn)
    for replacement in replacements:
        row = conn.execute(
            f"SELECT raw_result FROM qa_runs WHERE qa_requirement_id={p} "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (int(replacement["requirement_id"]),),
        ).fetchone()
        if row and (machine := run_machine(conn, row["raw_result"])):
            machines.add(machine)
    if len(machines) > 1:
        raise ValueError(
            "qa_correction_hosts_conflict: corrected cases ran on different hosts; "
            "run each corrected host roster separately with --machine NAME"
        )
    return next(iter(machines), None)
