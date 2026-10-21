"""Host custody checks a reconciliation runs before it releases any lease.

A held host lease is released only after its recovery is recorded; until
then reconciliation records cancellation (marked as its own) so a covering
steering seat may reset the host, and refuses with the exact command.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_plan_execution_abort_reason import (
    ABORT_REASON_MAX_LENGTH,
    REASON_DETAIL_SEPARATOR,
)
from yoke_core.domain.qa_plan_execution_abort_state import (
    abort_request,
    host_cleanup_proven,
    record_abort_request,
)
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

#: The code a reconciled execution's release reason opens with.
RECONCILED_REASON = "qa-plan-operator-reconciled"


def held_leases(conn: Any, execution: dict[str, Any]) -> tuple[list, list]:
    """Split active leases into held hosts and a mission's own review lease.

    A mission awaiting review keeps its primary lease on purpose so review can
    finish before teardown; that lease is custody bookkeeping, not a host in
    an unknown state, so it needs no recovery proof.
    """
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.qa_plan_execution_lifecycle import (
        _mission_needs_retained_lease,
    )
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    hosts = {lease.id: lease for lease in execution_host_leases(conn, execution)}
    review = []
    primary = execution.get("machine_lease_id")
    if primary is not None:
        claim = get_claim(conn, int(primary))
        mission_review = execution["state"] in {"walking", "awaiting_walk_review"} and (
            _mission_needs_retained_lease(execution)
        )
        if claim.is_active and mission_review:
            review.append(claim)
        elif claim.is_active:
            hosts[claim.id] = claim
    return sorted(hosts.values(), key=lambda lease: int(lease.id)), review


def recovery_request(conn: Any, execution: dict[str, Any], reason: str) -> dict:
    """Record cancellation, marked as reconcile's, so steering may reset hosts.

    An existing cancellation keeps its reason, ordinal and request time.
    """
    request = abort_request(execution)
    if request and request.get("reconcile"):
        return request
    if not request:
        detail = f"{RECONCILED_REASON}{REASON_DETAIL_SEPARATOR}{reason}"
        ordinal = min(int(execution["cursor_ordinal"]), len(execution["roster"]) - 1)
        request = {"reason": detail[:ABORT_REASON_MAX_LENGTH], "ordinal": ordinal}
    record_abort_request(conn, execution, {**request, "reconcile": True})
    conn.commit()
    return abort_request(execution)


def reconcile_pending(execution: dict[str, Any]) -> bool:
    """Whether an earlier reconcile already recorded this cancellation.

    The reset that run asked for borrows the execution's lease and renews its
    heartbeat, so its retry cannot prove staleness again; the first run did.
    """
    return bool((abort_request(execution) or {}).get("reconcile"))


def host_recovery_proven(conn: Any, execution: dict, request: dict) -> bool:
    from yoke_core.domain.agent_mission_restore import mission_restores_recorded

    ordinal = int(request["ordinal"])
    case = execution["roster"][ordinal]
    if case.get("runner_id") == "agent_mission" and mission_restores_recorded(
        conn, execution
    ):
        return True
    return host_cleanup_proven(conn, execution, ordinal)


def host_recovery_refusal(
    execution: dict, request: dict, leases: list[Any], project: str, retry: str
) -> QaPlanExecutionStateError:
    case = execution["roster"][int(request["ordinal"])]
    baseline = case.get("host_baseline")
    if baseline and case.get("starting_state") != "as_is":
        lead = "reset each held host to the interrupted case's declared baseline"
        steps = [
            f"yoke test-machine reset --project {project} --machine "
            f"{lease.target.machine_id} --baseline {baseline}"
            for lease in leases
        ]
    else:
        lead = (
            "release each held lease deliberately, because this case declares "
            "no baseline to reset to; manual release records the reset the "
            "next holder owes"
        )
        steps = [
            "yoke claims coordination-claim operator-release "
            + ("" if lease.key.startswith("QA_HOST:") else f"--project {project} ")
            + f"--key {lease.key} --claim-id {lease.id} --holder-session-id "
            f'{lease.session_id} --reason "<why>"'
            for lease in leases
        ]
    return QaPlanExecutionStateError(
        f"qa_reconcile_host_recovery_required: execution {execution['id']} still "
        f"holds lease(s) {', '.join(str(lease.id) for lease in leases)} and no "
        "host recovery is recorded. Cancellation is recorded, so a covering "
        f"steering seat may now {lead}: "
        + "; ".join(f"`{step}`" for step in steps)
        + f". Then retry `{retry}`. "
        "Nothing else changed."
    )


__all__ = [
    "RECONCILED_REASON",
    "held_leases",
    "host_recovery_proven",
    "host_recovery_refusal",
    "reconcile_pending",
    "recovery_request",
]
