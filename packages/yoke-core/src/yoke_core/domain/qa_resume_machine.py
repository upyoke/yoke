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
    test_machine = (document.get("evidence") or {}).get("test_machine")
    if test_machine:
        return validate_test_machine_resource_name(test_machine)
    lease = (document.get("host_control_submission") or {}).get("lease_id")
    return get_claim(conn, int(lease)).target.test_machine if lease else None


def execution_machine(
    conn: Any, execution: Mapping[str, Any], case: Mapping[str, Any]
) -> str | None:
    """Recover a single-host case's platform host from custody and run history.

    A slotted case resumes through :func:`execution_host_set`.
    """
    from yoke_core.domain.machine_qa_case_hosts import case_slots

    if case_slots(case):
        return None

    from yoke_core.domain.machine_qa_case_platform import case_platform
    from yoke_core.domain.machine_qa_host_rows import test_machine_rows
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    hosts = {
        row.test_machine: row.settings["os"]
        for row in test_machine_rows(conn)
    }

    platform = case_platform(case)

    def matches(test_machine: str | None) -> bool:
        if test_machine and platform is not None and test_machine not in hosts:
            raise ValueError(
                f"qa_resume_host_unregistered: recorded host {test_machine!r} is no longer "
                "registered for this project; restore its Test Machine registration "
                "before resuming so its preserved state is not lost"
            )
        return bool(test_machine) and (platform is None or hosts.get(test_machine) == platform)

    p = marker(conn)
    seen = set()
    while str(execution["id"]) not in seen:
        seen.add(str(execution["id"]))
        if execution.get("test_machine_lease_id"):
            test_machine = get_claim(
                conn, int(execution["test_machine_lease_id"])
            ).target.test_machine
            if matches(test_machine):
                return test_machine
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
                    test_machine = run_machine(conn, by_id[run_id])
                    if matches(test_machine):
                        return test_machine
        source = execution.get("continues_execution_id")
        if not source:
            return None
        execution = select_plan_execution(conn, str(source), lock=False)
    raise ValueError(
        "qa_resume_history_cycle: execution continuation history repeats; "
        "ask the control-plane operator to repair its source links before resuming"
    )


def execution_host_set(
    conn: Any, execution: Mapping[str, Any], case: Mapping[str, Any]
) -> tuple[str, tuple[str, ...]] | None:
    """The driver and companions still leased to a slotted *case*.

    Read from the execution's active leases bound to the case's requirement
    and ``companion-<id>``. ``None`` when the case is unbound or any slot's
    lease is gone: custody of the whole set is lost.
    """
    from yoke_core.domain.machine_qa_case_hosts import case_slots
    from yoke_core.domain.qa_case_host_custody import (
        bound_case_hosts,
        case_host_lease_id,
    )

    bound = bound_case_hosts(conn, dict(execution), dict(case))
    driver_lease = case_host_lease_id(conn, dict(execution), dict(case))
    driver = next((name for name, lease in bound.items() if lease == driver_lease), None)
    if driver is None or len(bound) < len(case_slots(case)):
        return None
    return driver, tuple(sorted(set(bound) - {driver}))
