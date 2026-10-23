"""Cooperative host aborts retain custody until required cleanup is proven."""

import json

from yoke_contracts.timestamps import format_instant, utc_now

from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    canonical,
    marker,
    result_rows,
)


def abort_request(execution):
    from yoke_core.domain.qa_plan_execution_reentry import PAUSE_REASON

    reason = str(execution.get("release_reason") or "")
    checkpoint = (
        json.loads(reason[len(PAUSE_REASON) :])
        if reason.startswith(PAUSE_REASON)
        else {}
    )
    return checkpoint.get("abort")


def owed_host_abort(conn, execution, *, reason):
    """Return the abort request held hosts still owe cleanup for, or None.

    A recorded agent_mission request stays owed while the mission holds its
    machine lease: only its walk-end teardown releases that host.
    """
    from yoke_core.domain.qa_plan_execution_reentry import PAUSE_REASON
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    if not execution.get("machine_lease_id") and not execution_host_leases(
        conn, execution
    ):
        return None
    roster = execution.get("roster") or []
    cursor = int(execution["cursor_ordinal"])
    request = abort_request(execution)
    prior = str(execution.get("release_reason") or "")
    if not request and not prior.startswith(PAUSE_REASON):
        return None  # Admission alone never starts credential-local host work.
    if not request:
        checkpoint = json.loads(prior[len(PAUSE_REASON) :])
        if not any(
            key in checkpoint for key in ("case_inflight", "checkin_cursor", "phase")
        ):
            return None  # Admission without a runner check-in never starts host work.
    ordinal = (
        int(request["ordinal"])
        if request
        else min(
            json.loads(prior[len(PAUSE_REASON) :]).get("case_inflight", cursor),
            len(roster) - 1,
        )
    )
    runner = roster[ordinal].get("runner_id")
    if runner == "agent_mission" and request:
        from yoke_core.domain.agent_mission_restore import mission_restores_recorded

        return (
            request
            if execution.get("machine_lease_id")
            and not mission_restores_recorded(conn, execution)
            else None
        )
    if runner != "host_control":
        return None
    if host_cleanup_proven(conn, execution, ordinal):
        return None
    return request or {"reason": reason, "ordinal": ordinal}


def record_abort_request(conn, execution, request):
    """Record cancellation in the checkpoint; custody and state stay as they are."""
    from yoke_core.domain.qa_plan_execution_reentry import (
        PAUSE_REASON,
        inflight_checkpoint,
    )

    checkpoint = json.loads(inflight_checkpoint(execution)[len(PAUSE_REASON) :])
    checkpoint["abort"] = dict(request)
    checkpoint["abort"].setdefault("requested_at", format_instant(utc_now()))
    encoded = PAUSE_REASON + canonical(checkpoint)
    conn.execute(
        f"UPDATE qa_plan_executions SET release_reason={marker(conn)} WHERE id={marker(conn)}",
        (encoded, str(execution["id"])),
    )
    execution["release_reason"] = encoded


_MISSION_WALK_END = (
    "qa_abort_walk_end_required: this mission's cancellation is recorded and it "
    "keeps its Test Machine lease until teardown. Its original session must run "
    "the dispatched `yoke qa mission walk-end` command, which removes staged "
    "secrets, restores starting state and releases the host; the abort settles "
    "there. For deliberate custody recovery, stop the runner and recover the "
    "host starting state, then have the holder or a covering steering seat "
    "release the host claim; manual release cancels the execution."
)


def _ended_owner_recovery(conn, execution):
    """Name steering reconciliation when no session is left to run walk-end."""
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.qa_plan_execution_reconcile import (
        execution_project,
        reconcile_command,
    )

    owner = query_one(
        conn,
        "SELECT ended_at,terminated_at FROM harness_sessions WHERE session_id=%s",
        (str(execution.get("session_id") or ""),),
    )
    if owner is not None and not (owner["ended_at"] or owner["terminated_at"]):
        return ""
    _project_id, project = execution_project(conn, execution)
    return (
        f" Its original session {execution.get('session_id')} has ended, so no "
        "walk-end can run: a live steering seat covering the project settles "
        f"it with `{reconcile_command(project, str(execution['id']))}`."
    )


def require_host_restored(conn, execution, *, reason, commit):
    """Persist cancellation before refusing an unproven host release."""
    request = owed_host_abort(conn, execution, reason=reason)
    if request is None:
        return
    ordinal = int(request["ordinal"])
    if execution["roster"][ordinal].get("runner_id") == "agent_mission":
        raise QaPlanExecutionStateError(
            _MISSION_WALK_END + _ended_owner_recovery(conn, execution)
        )
    if not commit:
        raise QaPlanExecutionStateError(
            "qa_abort_restore_required: in-flight host work must stop and record "
            "cleanup, including restoration of any declared baseline, before "
            "this operation can settle it. Run `yoke qa plan "
            "abort` for this execution's item, deployment run or standalone "
            "project and keep its runner connected through cleanup. Retry only "
            "after cleanup proof is recorded; if the runner is gone or cleanup "
            "fails, have the lease holder or a covering steering seat reset the "
            "host to the interrupted case's declared baseline, then retry abort. No caller changes were committed."
        )
    record_abort_request(conn, execution, request)
    conn.commit()
    raise QaPlanExecutionStateError(
        "qa_abort_restore_pending: cancellation is recorded; host custody is retained "
        "until the runner stops and records starting_state_restore cleanup proof. "
        "A declared baseline requires restored=true; an as_is case or a case "
        "without a baseline records that no restoration is required. Keep the "
        "runner connected and retry only after that proof is recorded. If the "
        "runner is gone or cleanup fails, stop that runner, then have the lease "
        "holder or a covering steering seat run `yoke test-machine reset --project P "
        "--test-machine TEST_MACHINE --baseline BASELINE` with the interrupted case's declared "
        "baseline, and retry this abort. The reset must succeed after cancellation "
        "was recorded; it retains the lease until abort settles. Without a declared "
        "baseline, recover the runner's no-restore cleanup receipt instead."
    )


def restore_cleanup_proven(restore, baseline):
    return restore.get("restored") is True and restore.get("baseline") == baseline


def host_cleanup_proven(conn, execution, ordinal):
    case = execution["roster"][ordinal]
    baseline = case.get("host_baseline")
    restore_required = case.get("starting_state") != "as_is" and bool(baseline)
    for row in result_rows(conn, str(execution["id"])):
        if row["ordinal"] != ordinal:
            continue
        result = row["result"]
        run = conn.execute(
            f"SELECT raw_result FROM qa_runs WHERE id={marker(conn)} AND qa_requirement_id={marker(conn)}",
            (result.get("run_id"), row["requirement_id"]),
        ).fetchone()
        if run is None:
            continue
        raw = run[0] if not hasattr(run, "keys") else run["raw_result"]
        evidence = (json.loads(raw) if isinstance(raw, str) else raw).get(
            "evidence"
        ) or {}
        restore = evidence.get("starting_state_restore") or {}
        if restore_required:
            if restore_cleanup_proven(restore, baseline):
                return True
        elif restore:
            return True
    if restore_required:
        from yoke_core.domain.qa_plan_abort_reset import reset_cleanup_proven

        return reset_cleanup_proven(conn, execution, baseline)
    return False


def settle_host_abort(conn, execution):
    request = abort_request(execution)
    if request and host_cleanup_proven(conn, execution, int(request["ordinal"])):
        from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

        finish_plan_execution(
            conn, execution, state="aborted", reason=request["reason"], commit=False
        )
