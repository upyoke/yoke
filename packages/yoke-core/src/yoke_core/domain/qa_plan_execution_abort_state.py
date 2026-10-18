"""Cooperative host aborts retain custody until the runner proves restoration."""

import json

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


def require_host_restored(conn, execution, *, reason, commit):
    """Persist cancellation before refusing an unproven host release."""
    from yoke_core.domain.qa_plan_execution_reentry import (
        PAUSE_REASON,
        inflight_checkpoint,
    )
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    if not execution.get("machine_lease_id") and not execution_host_leases(
        conn, execution
    ):
        return
    roster = execution.get("roster") or []
    if not any(case.get("runner_id") == "host_control" for case in roster):
        return
    cursor = int(execution["cursor_ordinal"])
    request = abort_request(execution)
    prior = str(execution.get("release_reason") or "")
    if not request and not prior.startswith(PAUSE_REASON):
        return  # Admission alone never starts credential-local host work.
    ordinal = (
        int(request["ordinal"])
        if request
        else min(
            json.loads(prior[len(PAUSE_REASON) :]).get("case_inflight", cursor),
            len(roster) - 1,
        )
    )
    if host_restored(conn, execution, ordinal):
        return
    if not commit:
        raise QaPlanExecutionStateError(
            "qa_abort_restore_required: in-flight host work must stop and prove "
            "restoration before this operation can settle it. Run `yoke qa plan "
            "abort` for this execution's item, deployment run or standalone "
            "project, keep its runner connected through cleanup, then retry "
            "this operation. No caller changes were committed."
        )
    checkpoint = json.loads(inflight_checkpoint(execution)[len(PAUSE_REASON) :])
    checkpoint["abort"] = request or {"reason": reason, "ordinal": ordinal}
    encoded = PAUSE_REASON + canonical(checkpoint)
    conn.execute(
        f"UPDATE qa_plan_executions SET release_reason={marker(conn)} WHERE id={marker(conn)}",
        (encoded, str(execution["id"])),
    )
    conn.commit()
    execution["release_reason"] = encoded
    raise QaPlanExecutionStateError(
        "qa_abort_restore_pending: cancellation is recorded; host custody is retained "
        "until the runner stops and records starting_state_restore proof. Keep the "
        "runner connected and retry abort after cleanup. If the runner is gone or "
        "restoration fails, ask the control-plane operator to recover the host and "
        "record verified restore evidence before releasing custody."
    )


def host_restored(conn, execution, ordinal):
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
        if restore.get("restored") is True and restore.get("baseline") == execution[
            "roster"
        ][ordinal].get("host_baseline"):
            return True
    return False


def settle_host_abort(conn, execution):
    request = abort_request(execution)
    if request and host_restored(conn, execution, int(request["ordinal"])):
        from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

        finish_plan_execution(
            conn, execution, state="aborted", reason=request["reason"], commit=False
        )
