"""Requirement-to-driver custody on the execution's physical host claims."""

from typing import Any

from yoke_core.domain.claim_chain_state import record_claim_reason
from yoke_core.domain.coordination_claims import get_claim

HOST_SET_REASON = "qa-plan-hosts:"


def claim_execution_id(reason: str | None) -> str:
    value = reason or ""
    if not value.startswith(HOST_SET_REASON):
        return ""
    return value[len(HOST_SET_REASON):].partition(":")[0]


def _case_ids(reason: str | None) -> set[str]:
    return set((reason or "").split(":", 2)[-1].split(",")) - {""}


def bind_case_host(
    conn: Any, execution: dict, case: dict, lease_id: int, *, companion: bool = False
) -> None:
    claim = get_claim(conn, lease_id)
    prefix = HOST_SET_REASON + str(execution["id"])
    requirements = _case_ids(claim.reason) if (claim.reason or "").startswith(prefix + ":") else set()
    requirement_id = str(case["requirement_id"])
    requirements.add("companion-" + requirement_id if companion else requirement_id)
    record_claim_reason(
        conn, claim_id=lease_id, reason=prefix + ":" + ",".join(sorted(requirements))
    )


def case_host_lease_id(conn: Any, execution: dict, case: dict) -> int | None:
    """Resolve the case's driver, including an in-flight pre-upgrade walk."""
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    prefix = HOST_SET_REASON + str(execution["id"]) + ":"
    requirement = str(case["requirement_id"])
    for claim in execution_host_leases(conn, execution):
        if (claim.reason or "").startswith(prefix) and requirement in _case_ids(claim.reason):
            return claim.id

    primary_id = execution.get("test_machine_lease_id")
    if primary_id is not None:
        primary = get_claim(conn, int(primary_id))
        if not (primary.reason or "").startswith(prefix):
            # Old captures already record the issued lease on the result. Only
            # grant the old primary to the matching captured case.
            from yoke_core.domain.qa_plan_execution_store import result_rows

            for row in result_rows(conn, str(execution["id"])):
                if int(row["requirement_id"]) != int(requirement):
                    continue
                result = row["result"] or {}
                recorded = result.get("lease_id")
                if recorded is None and (run_id := result.get("run_id")):
                    from yoke_core.domain.qa_resume_machine import run_machine
                    from yoke_core.domain.qa_plan_execution_store import marker

                    run = conn.execute(
                        f"SELECT raw_result FROM qa_runs WHERE id={marker(conn)}",
                        (int(run_id),),
                    ).fetchone()
                    if run and run_machine(conn, run[0]) == primary.target.test_machine:
                        return int(primary_id)
                if recorded is not None and int(recorded) == int(primary_id):
                    return int(primary_id)
                return None
            # During rollout, the current case can still submit its admission.
            cursor = int(execution.get("cursor_ordinal", 0))
            if cursor < len(execution["roster"]) and execution["roster"][cursor] == case:
                return int(primary_id)
    return None
