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


def operation_mission(conn: Any, *, lease_id: int, project: str, actor: Any) -> Any:
    """Lock the durable mission before its host claim, matching plan close-out."""
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
        f"SELECT id FROM qa_plan_executions WHERE machine_lease_id={p} OR id={p}",
        (lease.id, companion),
    ).fetchone()
    if row is None:
        return None
    execution = lock_plan_execution(conn, str(row["id"]))
    missions = [
        case
        for case in execution["roster"]
        if case.get("runner_id") == "agent_mission" and case.get("project") == project
    ]
    if execution["state"] != "awaiting_agent_review" or not missions:
        raise MachineQaProtocolError(
            "mission_operation_unavailable: the host belongs to a plan outside "
            "its mission walk; resume the owning mission before retrying the operation"
        )
    if not same_owner(execution, actor_id=actor.actor_id, session_id=actor.session_id):
        raise MachineQaProtocolError(
            "mission_operation_foreign_holder: the mission belongs to a different "
            "session or actor; ask its holder to perform the operation or wait for "
            "the mission to finish"
        )
    return execution


def begin_operation_execution(
    conn: Any, *, actor: Any, project: str, machine: str | None, **shape: Any
) -> Any:
    candidate = load_test_machine_contract(conn, project=project, machine=machine)
    lease = active_claim(conn, host_claim_target(candidate.settings["resource_name"]))
    mission = (
        None
        if lease is None
        else operation_mission(
            conn,
            lease_id=lease.id,
            project=project,
            actor=actor,
        )
    )
    if mission is None:
        return begin_host_control_execution(
            conn,
            project=project,
            session_id=actor.session_id,
            machine=machine,
            select_any=False,
            **shape,
        )
    lease, candidate = _validate_lease_owner(
        conn,
        project=project,
        session_id=actor.session_id,
        actor_id=actor.actor_id,
        lease_id=lease.id,
        allow_released=False,
    )
    contract = _issue(candidate, lease, cases=(), **shape)
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
