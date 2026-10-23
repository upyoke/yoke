"""Operator operations borrow an awaiting mission's host without settling it."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from yoke_core.domain.coordination_claims import (
    CoordinationClaimNotFoundError,
    active_claim,
    get_claim,
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
from yoke_core.domain.qa_plan_host_leases import HOST_SET_REASON
from yoke_core.domain.qa_plan_execution_lifecycle import heartbeat_plan_execution
from yoke_core.domain.schema_common import _table_exists


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
    if not lease.is_active or not _table_exists(conn, "qa_plan_executions"):
        return None
    p = marker(conn)
    companion = (lease.reason or "").removeprefix(HOST_SET_REASON)
    row = conn.execute(
        f"SELECT id FROM qa_plan_executions WHERE test_machine_lease_id={p} OR id={p}",
        (lease.id, companion),
    ).fetchone()
    if row is None:
        return None
    execution = lock_plan_execution(conn, str(row["id"]))
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
            and runner in {"host_control", "agent_mission"}
            and plan_execution_id == str(execution["id"])
        ):
            return execution
    missions = [
        case
        for case in execution["roster"]
        if case.get("runner_id") == "agent_mission" and case.get("project") == project
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
    **shape: Any,
) -> Any:
    candidate = load_test_machine_contract(conn, project=project, test_machine=test_machine)
    lease = active_claim(conn, host_claim_target(candidate.settings["resource_name"]))
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
        return begin_host_control_execution(
            conn,
            project=project,
            session_id=actor.session_id,
            test_machine=test_machine,
            select_any=False,
            **shape,
        )
    if shape.get("baselines") and mission["state"] in {"walking", "awaiting_walk_review"}:
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


def finish_operation_execution(
    conn: Any, lease: Any, *, mission: Any, reason: str
) -> bool:
    """Only the plan's own close-out releases a borrowed mission host."""
    if mission is None:
        complete_host_control_execution(conn, lease, reason=reason)
        return True
    heartbeat_plan_execution(conn, mission)
    return False


def repeated_mission_receipt(parsed: Any, recorded: Any, mission: Any) -> Any:
    """Identical retries adopt evidence; a later walk operation replaces it."""
    if mission is None or recorded is None:
        return recorded
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
    checks = deepcopy(parsed.checks)
    if parsed.operation == "screenshot":
        from yoke_core.domain.handlers.machine_qa_screenshot_artifact import (
            replay_screenshot,
        )

        replay_screenshot(parsed, recorded)
    matches = all(
        recorded[key] == getattr(parsed, key)
        for key in ("status", "checks", "error_code")
    )
    parsed.checks = checks
    return recorded if matches else None
