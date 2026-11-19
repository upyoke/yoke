"""Re-freeze a waiting deployment QA execution to its owner's current target.

A release takeover moves an execution to the successor run with the target
the predecessor froze. Once the successor deploys, that target names a build
the destination no longer serves, and the controller refuses to begin it.
An execution that has not begun (waiting or re-begun by its owner, no host
lease, cursor at zero and no recorded result) holds nothing tied to the old
build, so when its owner resumes it, it takes the roster and target ``begin``
built now in place: its id, ``execution_order`` and host-line place stay. A
begun execution keeps the target its results prove.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_plan_execution_store import canonical, marker, result_rows


def unbegun(conn: Any, execution: dict[str, Any]) -> bool:
    """Whether ``execution`` has run, leased and recorded nothing.

    An owner's ``active`` row qualifies too: its controller re-begins after a
    stale-target refusal, before it takes any host lease.
    """
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    return (
        execution["state"] in {"waiting", "active"}
        and execution.get("test_machine_lease_id") is None
        and int(execution.get("cursor_ordinal") or 0) == 0
        and not result_rows(conn, str(execution["id"]))
        and not execution_host_leases(conn, execution)
    )


def refreeze_unbegun_execution(
    conn: Any, execution: dict[str, Any], prepared: Any
) -> bool:
    """Move an unbegun deployment execution onto ``prepared``'s target.

    ``prepared`` is the roster ``begin`` just built under the run lock for
    the same subject and session. Only a changed target re-freezes; the
    caller's resume then finds the roster current.
    """
    if (
        not execution.get("deployment_run_id")
        or str(execution.get("execution_target_digest") or "")
        == prepared.execution_target_digest
        or not unbegun(conn, execution)
    ):
        return False
    slot = marker(conn)
    conn.execute(
        f"UPDATE qa_plan_executions SET execution_target_json={slot},"
        f"execution_target_digest={slot},roster_json={slot},roster_digest={slot} "
        f"WHERE id={slot}",
        (
            canonical(prepared.execution_target),
            prepared.execution_target_digest,
            canonical(prepared.roster),
            prepared.digest,
            str(execution["id"]),
        ),
    )
    execution.update(
        execution_target=prepared.execution_target,
        execution_target_digest=prepared.execution_target_digest,
        roster=prepared.roster,
        roster_digest=prepared.digest,
    )
    return True


__all__ = ["refreeze_unbegun_execution", "unbegun"]
