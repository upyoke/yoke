"""A plan case whose Test Machine SSH cannot reach waits instead of erroring.

The executing machine reports the case unstarted with ``ssh_unavailable``.
The authority records that as the host's failed verification, so
``host_unhealthy`` bars it, and queues the plan on the host's line. A later
successful verify or golden capture heals the host and the line's turn wakes
the plan. Yoke never starts a stopped host; the operator does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoke_contracts.machine_qa_failures import SSH_UNAVAILABLE, HostControlLocalError

if TYPE_CHECKING:
    from yoke_harness.test_machine_operations import LocalHostControlSubmission
    from yoke_core.domain.machine_qa_execution_contract import (
        HostControlExecutionContract,
    )
    from yoke_core.domain.machine_qa_submission_recording import (
        MachineCaseSubmissionResult,
    )


def unreachable_submission(
    contract: "HostControlExecutionContract", error: HostControlLocalError
) -> "LocalHostControlSubmission":
    """Report the case unstarted because SSH never reached the host."""
    from yoke_harness.test_machine_operations import LocalHostControlSubmission
    from yoke_core.domain.machine_qa_submission_artifacts import (
        ensure_secret_free_result,
    )

    evidence = {
        "runner_id": "host_control",
        "machine": contract.settings["resource_name"],
        "baseline": contract.baselines[0] if contract.baselines else None,
        "case_started": False,
        "host_unreachable": {"detail": str(error), "recovery": error.recovery_hint},
    }
    payload: dict[str, Any] = {
        "lease_id": contract.lease_id,
        "contract_digest": contract.contract_digest,
        "results": [
            {
                "requirement_id": contract.cases[0].requirement_id,
                "case_outcome": "blocked_on_precondition",
                "verdict": "blocked",
                "evidence": evidence,
                "error_code": SSH_UNAVAILABLE,
                "duration_ms": 0,
                "artifacts": [],
            }
        ],
    }
    ensure_secret_free_result(payload)
    return LocalHostControlSubmission(payload=payload, artifact_paths=())


def wait_if_host_unreachable(
    conn: Any,
    execution: dict[str, Any],
    contract: "HostControlExecutionContract",
    result: "MachineCaseSubmissionResult",
) -> dict[str, Any] | None:
    """Mark an unreachable host unhealthy and queue the plan, uncommitted.

    Return None for any other result; it is recorded as the case verdict.
    """
    if (
        result.case_outcome != "blocked_on_precondition"
        or result.error_code != SSH_UNAVAILABLE
    ):
        return None
    from yoke_core.domain.machine_qa_execution_protocol import (
        commit_deferred_connection,
    )
    from yoke_core.domain.machine_verification_recording import (
        record_test_machine_verification,
    )
    from yoke_contracts.timestamps import format_instant
    from yoke_core.domain.qa_host_health import unhealthy_rationale
    from yoke_core.domain.qa_host_turns import record_host_wait

    machine = contract.settings["resource_name"]
    recorded = record_test_machine_verification(
        commit_deferred_connection(conn),
        contract.project_id,
        machine=machine,
        status="error",
        checks=[result.evidence],
        error_code=SSH_UNAVAILABLE,
    )
    health = {
        "machine": machine,
        "error_code": SSH_UNAVAILABLE,
        "checked_at": format_instant(recorded["checked_at"]),
    }
    return record_host_wait(
        conn,
        execution,
        machine=machine,
        rationale=unhealthy_rationale(health),
        commit=False,
    )


__all__ = ["unreachable_submission", "wait_if_host_unreachable"]
