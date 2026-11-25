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

from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    canonical,
    marker,
    result_rows,
)


def unbegun(conn: Any, execution: dict[str, Any]) -> bool:
    """Whether ``execution`` has run, leased, admitted and recorded nothing.

    An owner's ``active`` row qualifies too: its controller re-begins after a
    stale-target refusal, before it takes any host lease. A host-turn wait is
    a check-in pause at cursor zero; a pause in any other phase, an admitted
    or in-flight case, or a capture of the first case means a case may have
    acted, so its target stays.
    """
    from yoke_core.domain.qa_plan_execution_reentry import pause_checkpoint
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    pause = pause_checkpoint(execution)
    return (
        execution["state"] in {"waiting", "active"}
        and execution.get("test_machine_lease_id") is None
        and int(execution.get("cursor_ordinal") or 0) == 0
        and pause.get("phase", "checkin") == "checkin"
        and not {"case_admitted", "case_inflight"} & set(pause)
        and not result_rows(conn, str(execution["id"]))
        and not execution_host_leases(conn, execution)
        and not _captured(conn, execution)
    )


def _captured(conn: Any, execution: dict[str, Any]) -> bool:
    """A capture of the first case exists, though no result was recorded."""
    roster = execution.get("roster") or []
    if not roster:
        return False
    slot = marker(conn)
    return (
        conn.execute(
            f"SELECT 1 FROM qa_runs WHERE qa_requirement_id={slot} "
            f"AND created_at >= {slot} LIMIT 1",
            (int(roster[0]["requirement_id"]), execution["created_at"]),
        ).fetchone()
        is not None
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


def _current_digest(conn: Any, execution: dict[str, Any]) -> str | None:
    """The owning run's current target digest for this execution's subject."""
    from yoke_core.domain.qa_execution_environment_target import target_digest

    run_id = str(execution["deployment_run_id"])
    stage = str(execution["deployment_stage"])
    member = execution.get("deployment_member_item_id")
    if member is None:
        from yoke_core.domain.deployment_qa_plan_group_rebind import (
            current_group_target,
        )
        from yoke_core.domain.deployment_qa_plan_groups import group_for_target
        from yoke_core.domain.deployment_qa_stage_contract import _run_stage

        group = group_for_target(conn, run_id, execution["execution_target"])
        if group is None or not group.open:
            return None
        run = _run_stage(conn, run_id, stage, require_active=False)
        return target_digest(current_group_target(conn, run, group))
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )

    subject = deployment_qa_stage_subject(
        conn, run_id=run_id, stage_name=stage, member_item_id=int(member)
    )
    return target_digest(deployment_qa_execution_target(conn, subject))


def _resume_moved_walk(conn: Any, execution: dict, parsed: Any, actor: Any) -> dict:
    """Resume the one admitted partition under item, run, and cursor locks."""
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )
    from yoke_core.domain.deployment_runs_lock import run_lock_held
    from yoke_core.domain.qa_plan_execution_authority import (
        lock_member_admission,
        require_plan_execution_owner,
    )
    from yoke_core.domain.qa_plan_execution_begin_admission import PreparedRoster, prepare_roster
    from yoke_core.domain.qa_plan_execution_reentry import resume_execution
    from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
    from yoke_core.domain.qa_plan_partition_chains import partition_key
    from yoke_core.domain.qa_walk_authority import admitted_walk, require_admitted_walk_claim

    execution_id = str(execution["id"])
    run_id = str(execution["deployment_run_id"])
    stage = str(execution["deployment_stage"])
    member = int(execution["deployment_member_item_id"])
    conn.rollback()  # Release the cursor lock before taking the item and run locks.
    lock_member_admission(conn, run_id, member)
    locked = lock_plan_execution(conn, execution_id)
    require_plan_execution_owner(
        locked, conn=conn, actor_id=actor.actor_id, session_id=actor.session_id,
        deployment_run_id=run_id, deployment_stage=stage,
        deployment_member_item_id=member,
    )
    if not admitted_walk(locked):
        raise QaPlanExecutionStateError(
            "qa_resume_assignment_changed: inspect the execution's current assignment before resuming"
        )
    claim = require_admitted_walk_claim(conn, locked, item_id=member, lock=True)
    current = _current_digest(conn, locked)
    if current == locked["execution_target_digest"]:
        resume_execution(conn, locked)
        return locked
    if current is None or not unbegun(conn, locked):
        raise QaPlanExecutionStateError(
            "qa_resume_target_locked: preserve the existing cursor and its build evidence. "
            "Inspect the saved case checkpoint before recording or resuming."
        )
    with run_lock_held(conn, run_id):
        materialize_deployment_qa_stage(
            conn, deployment_run_id=run_id, deployment_stage=stage,
            deployment_member_item_id=member, commit=False,
        )
    # The same ordered requirement IDs must still form one partition on the
    # current target. A changed or split chain cannot select another cursor.
    key = partition_key([
        {**row, "execution_target_digest": current} for row in locked["roster"]
    ])
    prepared = prepare_roster(
        conn, item_id=None, transition_id=None, deployment_run_id=run_id,
        deployment_stage=stage, deployment_member_item_id=member,
        expected_target=None, expected_target_digest=current, plan=None,
        host_capability_kinds=None, checkout_path=parsed.checkout_path,
        expected_branch=parsed.expected_branch, session_id=actor.session_id,
        test_machine=parsed.test_machine, partition=key,
        source_session_id=str(claim["session_id"]),
    )
    if (
        not isinstance(prepared, PreparedRoster)
        or prepared.execution_target_digest != current
        or [row["requirement_id"] for row in prepared.roster]
        != [row["requirement_id"] for row in locked["roster"]]
        or not refreeze_unbegun_execution(conn, locked, prepared)
    ):
        raise QaPlanExecutionStateError(
            "qa_resume_assignment_changed: preserve the saved cursor and ask the item "
            "holder to inspect the current partition and its ordered requirements"
        )
    resume_execution(conn, locked)
    return locked


def resume_moved_execution(
    conn: Any, execution: dict[str, Any], parsed: Any, actor: Any
) -> dict[str, Any] | None:
    """Re-freeze an unbegun execution whose owning run now serves another build.

    The host-turn wake resumes by execution id, which builds no roster. When
    the owning run's current target differs from the frozen one, the resume
    re-enters ``begin`` for the same subject and session: a member's cases
    rebind on materialization, a plan group's on its begin, and the owner path
    re-freezes this execution in place, keeping its id and ``execution_order``.
    ``None`` means an ordinary resume applies.
    """
    from yoke_core.domain.qa_walk_authority import admitted_walk

    if not execution.get("deployment_stage") or not unbegun(conn, execution):
        return None
    current = _current_digest(conn, execution)
    if current is None or current == str(execution.get("execution_target_digest") or ""):
        return None
    if execution.get("deployment_member_item_id") is not None and admitted_walk(execution):
        return _resume_moved_walk(conn, execution, parsed, actor)

    from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution

    run_id = str(execution["deployment_run_id"])
    stage = str(execution["deployment_stage"])
    member = execution.get("deployment_member_item_id")
    target = execution["execution_target"]
    conn.rollback()  # Release the ownership read; begin takes the run lock first.
    if member is not None:
        from yoke_core.domain.deployment_qa_stage_materialization import (
            materialize_deployment_qa_stage,
        )

        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=run_id,
            deployment_stage=stage,
            deployment_member_item_id=int(member),
        )
    begun = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=stage,
        deployment_member_item_id=None if member is None else int(member),
        plan=(
            str(target["deployment"]["shared_plan"]["plan_id"])
            if member is None
            else None
        ),
        checkout_path=parsed.checkout_path,
        expected_branch=parsed.expected_branch,
        test_machine=parsed.test_machine,
        actor_id=actor.actor_id,
        session_id=actor.session_id,
    )
    if str(begun.get("id") or "") != str(execution["id"]):
        raise QaPlanExecutionStateError(
            f"qa_resume_identity_mismatch: re-targeting execution {execution['id']} "
            f"to run {run_id}'s current target began {begun.get('id') or 'no execution'}; "
            "preserve both receipts and report to the control-plane operator"
        )
    from yoke_core.domain.qa_plan_execution_reentry import resume_if_paused

    resume_if_paused(conn, begun)  # a host-turn wait records its check-in pause
    return begun


__all__ = ["refreeze_unbegun_execution", "resume_moved_execution", "unbegun"]
