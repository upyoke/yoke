"""Settle a taken-over run as succeeded inside its takeover transaction.

A takeover without run-level QA or approval moves every member the older run
has not closed (:mod:`yoke_core.domain.deployment_run_target_takeover`). What
stays was closed there by its own passed item QA, so the older run already
delivered it and owes nothing more: it reads succeeded in the same
transaction that created the newer run, never ``executing`` without a driver.

Only database writes happen here. The carried-work record reads the
repository host and the delivery notices go to other sessions, so both run
after the creation commits (:func:`finish_settled_takeover`).
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import instant_parameter, utc_now

SETTLEMENT_REFUSED_CODE = "takeover_settlement_refused"


def _remaining_stages(conn: Any, old_id: str, stages: list[dict]) -> list[str]:
    row = conn.execute(
        "SELECT current_stage FROM deployment_runs WHERE id=%s", (old_id,)
    ).fetchone()
    names = [str(stage.get("name") or "") for stage in stages]
    current = str(row["current_stage"] or "") if row else ""
    return names[names.index(current) :] if current in names else []


def _advance_to_complete(
    conn: Any, old_id: str, stages: list[dict], delivered_to: str
) -> None:
    """Walk the cursor and member stamps to ``complete``, as a driver would.

    Every member is stamped in one statement, so the older run's lock covers
    the same work however many members it closed.
    """
    from yoke_core.domain.deployment_run_stage_entry import set_current_stage

    for stage in _remaining_stages(conn, old_id, stages):
        set_current_stage(conn, old_id, stage, only_executing=True)
    deployed_to = ", deployed_to=%(to)s" if delivered_to else ""
    conn.execute(
        f"UPDATE items SET deploy_stage='complete'{deployed_to}, updated_at=%(at)s "
        "WHERE id IN (SELECT item_id FROM deployment_run_items WHERE run_id=%(run)s)",
        {
            "to": delivered_to,
            "at": instant_parameter(conn, utc_now()),
            "run": old_id,
        },
    )
    set_current_stage(conn, old_id, "complete", only_executing=True)


def _delivered_to(conn: Any, old_id: str) -> str:
    row = conn.execute(
        "SELECT COALESCE(e.name, dr.target_tier, '') AS delivered_to "
        "FROM deployment_runs dr LEFT JOIN environments e "
        "ON e.id=dr.target_environment_id WHERE dr.id=%s",
        (old_id,),
    ).fetchone()
    return str(row["delivered_to"] or "") if row else ""


def succeed_taken_over_run(
    conn: Any, old_id: str, new_run_id: str, stages: list[dict]
) -> None:
    """Mark *old_id* succeeded on the caller's transaction, or refuse by name.

    The caller has already moved every unclosed member and retracted the
    memberless obligations nobody passed. A refusal here is the run's own
    succeeded gate, raised as a takeover refusal so nothing is created.
    """
    from yoke_core.domain.deployment_run_settle_success import (
        record_run_deliveries_on,
    )
    from yoke_core.domain.deployment_qa_stage_wake_withdraw import (
        withdraw_deployment_qa_wait_wakes,
    )
    from yoke_core.domain.deployment_run_completion_preconditions import (
        refuse_succeeded,
    )
    from yoke_core.domain.deployment_run_target_takeover import TakeoverRefused
    from yoke_core.domain.environment_delivery_record import stamp_run_environment

    _advance_to_complete(conn, old_id, stages, _delivered_to(conn, old_id))
    refusal = refuse_succeeded(conn, old_id)
    if refusal:
        raise TakeoverRefused(
            SETTLEMENT_REFUSED_CODE,
            f"run {old_id} keeps only members it already closed, but it cannot "
            f"read succeeded: {refusal.removeprefix('Error: ')} Nothing was "
            f"created or changed. Recovery: settle or waive what {old_id} still "
            f"owes (yoke deployment-runs get {old_id}), or end it with "
            f"yoke deployment-runs terminalize {old_id} --disposition cancelled "
            '--reason "<why>", then create this run again.',
        )
    completed_at = utc_now()
    conn.execute(
        "UPDATE deployment_runs SET status='succeeded', completed_at=%s WHERE id=%s",
        (instant_parameter(conn, completed_at), old_id),
    )
    stamp_run_environment(conn, old_id, when=completed_at)
    record_run_deliveries_on(conn, old_id)
    withdraw_deployment_qa_wait_wakes(
        conn,
        run_id=old_id,
        reason=f"run_terminal:succeeded (taken over by {new_run_id})",
    )


def finish_settled_takeover(conn: Any, new_run_id: str) -> Optional[str]:
    """After creation commits: cancel the superseded run's workflows, then
    record carried work and send delivery notices for a settled one.

    Returns the settled run's id, or ``None`` when this creation settled none.
    """
    from yoke_core.domain.deployment_delivery_close_out_notice import (
        notify_delivery_cleared,
    )
    from yoke_core.domain.deployment_run_carried_work import record_carried_work
    from yoke_core.domain.deployment_run_target_takeover import (
        SUPERSEDES_COLUMN,
        takeover_available,
    )

    if not takeover_available(conn):
        return None
    from yoke_core.domain.deployment_run_workflow_cancellation import (
        cancel_run_workflows,
    )

    row = conn.execute(
        f"SELECT old.id, old.status FROM deployment_runs new "
        f"JOIN deployment_runs old ON old.id = new.{SUPERSEDES_COLUMN} "
        "WHERE new.id = %s",
        (new_run_id,),
    ).fetchone()
    if row is None:
        return None
    old_id = str(row["id"])
    cancel_run_workflows(conn, old_id)
    if str(row["status"]) != "succeeded":
        return None
    record_carried_work(conn, old_id)
    conn.commit()
    notify_delivery_cleared(conn, run_id=old_id)
    return old_id


__all__ = [
    "SETTLEMENT_REFUSED_CODE",
    "finish_settled_takeover",
    "succeed_taken_over_run",
]
