"""Operator operations borrow an awaiting mission's host without settling it."""

from __future__ import annotations

from yoke_contracts.qa_case_starting_state import needs_test_machine

from typing import Any

from yoke_core.domain.coordination_claims import (
    CoordinationClaimNotFoundError,
    active_claim,
    get_claim,
    heartbeat,
)
from yoke_core.domain.host_control_runner import load_test_machine_contract
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaProtocolError,
    _issue,
    _validate_lease_owner,
    begin_host_control_execution,
    complete_host_control_execution,
)
from yoke_core.domain.qa_plan_execution_store import (
    lock_plan_execution,
    marker,
    same_owner,
)
from yoke_core.domain.qa_host_set_turns import reserved_wait
from yoke_core.domain.qa_host_turns import HOST_TURN_REASON
from yoke_core.domain.qa_plan_execution_lifecycle import heartbeat_plan_execution


def operation_caller_project(conn: Any, session_id: str) -> str:
    """Resolve the caller's QA project for a universe host operation."""
    row = conn.execute(
        "SELECT p.slug FROM harness_sessions s JOIN projects p ON p.id=s.project_id "
        f"WHERE s.session_id={marker(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise MachineQaProtocolError(
            "test_machine_operation_project_context_required: run the operation "
            "from a session in a project so Yoke can record its QA context"
        )
    return str(row[0])


def operation_mission(
    conn: Any,
    *,
    lease_id: int,
    project: str,
    actor: Any,
    operation=None,
    baselines=(),
    plan_execution_id: str | None = None,
) -> Any:
    """Lock the durable mission before its host claim, matching plan close-out.

    A plan names itself with *plan_execution_id* to refresh its host's golden
    under its own lease, before its machine case resets to that golden.
    """
    try:
        lease = get_claim(conn, lease_id)
    except CoordinationClaimNotFoundError:
        # The submission validator owns the diagnosed missing-lease refusal.
        return None
    if not lease.is_active:
        return None
    from yoke_core.domain.host_lease_walk_heartbeat import (
        lease_execution_id,
    )

    execution_id = lease_execution_id(conn, lease)
    if execution_id is None:
        return None
    execution = lock_plan_execution(conn, execution_id)
    from yoke_core.domain.qa_plan_abort_reset import require_abort_reset

    if require_abort_reset(
        conn,
        execution,
        lease=lease,
        project=project,
        actor=actor,
        operation=operation,
        baselines=baselines,
    ):
        return execution
    test_machine = str(lease.target.test_machine)
    if not same_owner(execution, actor_id=actor.actor_id, session_id=actor.session_id):
        raise MachineQaProtocolError(
            f"mission_operation_foreign_holder: you do not hold the lease on {test_machine}; "
            f"session {execution['session_id']} holds it for plan {execution['id']}. "
            "Declare method_config.test_machine on your QA case and run its scoped plan "
            "to acquire the host lease after that holder finishes"
        )
    if execution["state"] == "active":
        ordinal = int(execution["cursor_ordinal"])
        roster = execution["roster"]
        runner = roster[ordinal].get("runner_id") if ordinal < len(roster) else None
        if runner == "worktree_run":
            return execution
        if (
            operation == "golden_capture"
            and needs_test_machine(roster[ordinal])
            and plan_execution_id == str(execution["id"])
        ):
            return execution
    missions = [
        case
        for case in execution["roster"]
        if case.get("runner_id") == "agent_mission"
        and needs_test_machine(case)
        and case.get("project") == project
    ]
    if execution["state"] not in {"walking", "awaiting_walk_review"} or not missions:
        raise MachineQaProtocolError(
            f"mission_operation_unavailable: the lease on {test_machine} belongs to "
            f"your plan {execution['id']}, which is {execution['state']}; this "
            "operation requires its active declared-host Command case, an "
            "awaiting mission walk, or a golden capture naming the plan as "
            "plan_execution_id at its active machine case. Resume the scoped "
            "plan before retrying"
        )
    return execution


def begin_operation_execution(
    conn: Any,
    *,
    actor: Any,
    project: str,
    test_machine: str | None,
    plan_execution_id: str | None = None,
    automatic_reset: bool = False,
    **shape: Any,
) -> Any:
    candidate = load_test_machine_contract(
        conn, project=project, test_machine=test_machine
    )
    from yoke_core.domain.qa_host_queue import lock_host_queue

    name = candidate.settings["resource_name"]
    if automatic_reset:
        from yoke_contracts.machine_qa_execution import RESET_OPERATION
        from yoke_core.domain.machine_reset_debt import owed_reset

        lock_host_queue(conn)
        if plan_execution_id is not None or shape["operation"] != RESET_OPERATION:
            raise MachineQaProtocolError(
                "automatic_reset_requires_own_lease: begin a standalone reset"
            )
        if active_claim(conn, host_claim_target(name)) is not None:
            raise MachineQaProtocolError(
                "automatic_reset_skipped: the current holder will recover the host"
            )
        debt = owed_reset(conn, name)
        if debt is None or debt.attempt is not None or shape["baselines"] != [debt.baseline]:
            raise MachineQaProtocolError(
                "automatic_reset_skipped: this baseline is no longer owed for automatic reset"
            )
        return begin_host_control_execution(
            conn, project=project, session_id=actor.session_id,
            test_machine=name, select_any=False, **shape,
        )

    lease = active_claim(conn, host_claim_target(name))
    mission = (
        None
        if lease is None
        else operation_mission(
            conn,
            lease_id=lease.id,
            project=project,
            actor=actor,
            operation=shape.get("operation"),
            baselines=shape.get("baselines", ()),
            plan_execution_id=plan_execution_id,
        )
    )
    if mission is None and plan_execution_id is not None:
        raise MachineQaProtocolError(
            f"plan_golden_refresh_lease_missing: plan {plan_execution_id} does "
            f"not hold the lease on {candidate.settings['resource_name']}; its "
            "machine case must begin before it refreshes that host's golden. "
            "Rerun the QA plan"
        )
    if mission is None:
        lock_host_queue(conn)
        lease = active_claim(
            conn, host_claim_target(candidate.settings["resource_name"])
        )
    if mission is None and holds_plan_turn(conn, lease, actor):
        # Consuming the reservation would release the plan's turn on submit.
        lease, candidate = _validate_lease_owner(
            conn,
            project=project,
            session_id=actor.session_id,
            actor_id=actor.actor_id,
            lease_id=lease.id,
            allow_released=False,
        )
        from yoke_core.domain.qa_host_turn_borrow import borrow_turn

        contract = _issue(conn, candidate, lease, cases=(), **shape)
        borrow_turn(conn, lease, contract.contract_digest)
        return contract
    if mission is None:
        return begin_host_control_execution(
            conn,
            project=project,
            session_id=actor.session_id,
            test_machine=test_machine,
            select_any=False,
            **shape,
        )
    if shape.get("baselines") and mission["state"] in {
        "walking",
        "awaiting_walk_review",
    }:
        raise MachineQaProtocolError(
            "test_machine_cleanup_live_lease: you hold the lease on "
            f"{candidate.settings['resource_name']} for your awaiting mission "
            f"{mission['id']}; reset/verify would clear that mission's temporary "
            "state. Finish or abort your mission before resetting or verifying this host"
        )
    lease, candidate = _validate_lease_owner(
        conn,
        project=project,
        session_id=mission["session_id"],
        actor_id=mission["actor_id"],
        lease_id=lease.id,
        allow_released=False,
    )
    contract = _issue(conn, candidate, lease, cases=(), **shape)
    heartbeat_plan_execution(conn, mission)
    return contract


def holds_plan_turn(conn: Any, lease: Any, actor: Any) -> bool:
    """Whether *lease* is the caller's unconsumed reserved turn for a plan."""
    if lease is None or not lease.is_active or lease.session_id != actor.session_id:
        return False
    if not (lease.reason or "").startswith(HOST_TURN_REASON):
        return False
    wait = reserved_wait(conn, lease)
    return wait is not None and bool(wait["qa_plan_execution_id"])


def finish_operation_execution(
    conn: Any, lease: Any, *, mission: Any, reason: str, contract_digest: str
) -> bool:
    """Only the plan's own close-out releases a borrowed mission host.

    An operation run on its holder's reserved plan turn keeps that turn for the
    plan's own run: only that path reaches here with a host-turn reason, since
    every acquire rewrites the reason it consumes.
    """
    if mission is None and (lease.reason or "").startswith(HOST_TURN_REASON):
        from yoke_core.domain.qa_host_turn_borrow import finish_borrow

        finish_borrow(conn, lease, contract_digest)
        heartbeat(conn, lease.id)
        return False
    if mission is None:
        complete_host_control_execution(conn, lease, reason=reason)
        return True
    heartbeat_plan_execution(conn, mission)
    return False


def operation_replay_receipt(
    parsed: Any, recorded: Any, *, mission: Any, borrowed_turn: bool
) -> Any:
    """Replay matching results and allow new evidence on a retained plan lease."""
    if recorded is None:
        return None
    if mission is not None:
        from yoke_core.domain.qa_plan_execution_abort_state import abort_request
        from yoke_contracts.timestamps import parse_instant

        request = abort_request(mission)
        if (
            request
            and request.get("requested_at")
            and (
                parse_instant(recorded["performed_at"])
                <= parse_instant(request["requested_at"])
            )
        ):
            return None
    checks = parsed.checks
    if parsed.operation == "screenshot":
        from yoke_core.domain.machine_qa_screenshot_artifact import (
            replay_screenshot_checks,
        )

        checks = replay_screenshot_checks(checks, recorded["checks"])
    if (
        recorded["status"] == parsed.status
        and recorded["checks"] == checks
        and recorded["error_code"] == parsed.error_code
    ):
        return recorded
    if mission is not None or borrowed_turn:
        return None
    raise ValueError("replayed result differs from the recorded receipt")
