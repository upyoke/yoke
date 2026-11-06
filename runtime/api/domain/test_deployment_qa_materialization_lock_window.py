"""Deployment QA writers read before the run row lock and hold it only to write.

On a 33-member run, one member's materialize once held the
``deployment_runs`` row lock for minutes while it re-derived every member's
plan groups one query at a time, and every other writer queued behind it.
These runs share one shape at two sizes: every statement count must be the
same at 3 members and at 33, inside and outside the lock. A member writes
only its own item cases; each attached plan runs as one plan group.
"""

from __future__ import annotations

from runtime.api.domain.deployment_qa_materialization_lock_window_test_support import (
    LockWindowRecorder as LockWindowRecorder,
    STAGE as STAGE,
    _seed as _seed,
)


from yoke_core.domain.deployment_qa_materialization_write import (
    write_under_run_lock,
)
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

SIZES = (("run-lock-window-small", 13001, 3), ("run-lock-window-large", 14001, 33))
_RUN_LOCKS = (
    "FROM deployment_runs WHERE id=%s FOR UPDATE",
    "FROM deployment_runs WHERE id=%s ORDER BY",
)


def _measure(conn, write) -> tuple[int, int]:
    recorder = LockWindowRecorder(conn)
    write(recorder)
    return recorder.counts()


def _materialize(run_id, member):
    return lambda conn: materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=member,
    )


def _form_groups(run_id):
    """Form the run's plan groups the way a dispatch does: under the run lock."""
    return lambda conn: write_under_run_lock(
        conn, run_id, lambda: ensure_groups(conn, run_id, STAGE)
    )


def test_member_writes_cost_the_same_at_any_run_size(test_db):
    """A member's item cases and the run's plan groups cost the same at any size."""
    measured = {}
    for run_id, first, size in SIZES:
        members = _seed(test_db, run_id, first, size)
        measured[size] = {
            "first": _measure(test_db, _materialize(run_id, members[0])),
            "repeat": _measure(test_db, _materialize(run_id, members[0])),
            "peer": _measure(test_db, _materialize(run_id, members[1])),
            "groups": _measure(test_db, _form_groups(run_id)),
            "groups again": _measure(test_db, _form_groups(run_id)),
        }
    small, large = measured[3], measured[33]
    assert large == small, f"statement counts grew with members: {measured}"
    for name in ("first", "repeat", "peer"):
        total, locked = large[name]
        # Most of the work is the unlocked read; the lock covers the writes.
        assert locked < total, measured


def test_a_membership_change_during_the_read_is_read_again(test_db, monkeypatch):
    """A peer leaving between the read and the lock is read again, unshared."""
    from yoke_core.domain import deployment_qa_materialization_projection as module
    from yoke_core.domain.deployment_qa_plan_groups import attached_plans
    from yoke_core.domain.deployment_run_member_removal import remove_members_on

    run_id = "run-lock-window-moved"
    first, peer = _seed(test_db, run_id, 15001, 2, requirements=1)
    reads = []
    real = module.MaterializationProjection.__init__

    def read(self, conn, run, **kwargs):
        real(self, conn, run, **kwargs)
        reads.append(len(self.members()))
        if len(reads) == 1:
            # Committed after the fingerprint, before the run row lock.
            remove_members_on(test_db, run_id, [peer], reason="moved mid-read")
            test_db.commit()

    monkeypatch.setattr(module.MaterializationProjection, "__init__", read)
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=first,
    )
    assert reads == [2, 1]  # both members on the stale read, one once re-read
    owners = {
        row[0]
        for row in test_db.execute(
            "SELECT deployment_member_item_id FROM qa_requirements WHERE id=ANY(%s)",
            (result["created_requirement_ids"],),
        ).fetchall()
    }
    assert peer not in owners
    assert all(
        members == [first] for members in attached_plans(test_db, run_id).values()
    )


def test_member_removal_costs_the_same_at_any_run_size(test_db, monkeypatch):
    from yoke_core.domain import deployment_run_member_removal as removal

    measured = {}
    for run_id, first, size in SIZES:
        members = _seed(test_db, run_id, first, size)
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=members[0],
        )
        _form_groups(run_id)(test_db)
        # Its plan groups are still open, so the guard lets it leave the run.
        test_db.execute("UPDATE items SET status='release' WHERE id=%s", (members[0],))
        test_db.commit()
        recorder = LockWindowRecorder(test_db)
        recorder.close = lambda: None  # the command closes its connection
        monkeypatch.setattr(removal, "connect", lambda _path=None: recorder)
        message = removal.cmd_remove_item(
            run_id, members[0], reason="split out of the release"
        )
        assert message.startswith("Removed YOK-"), message
        measured[size] = recorder.counts()
    assert measured[33] == measured[3], measured


def _lock_windows(recorder) -> list[int]:
    windows, current = [], 0
    for locked, _text in [*recorder.statements, (False, "")]:
        if locked:
            current += 1
        elif current:
            windows.append(current)
            current = 0
    return windows


def test_a_dispatch_commits_each_member_under_its_own_run_lock(test_db):
    """No lock window grows with the cohort; groups form in a separate write."""
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        materialize_and_gate_deployment_qa_stage,
    )

    widest = {}
    for run_id, first, size in SIZES:
        members = _seed(test_db, run_id, first, size, requirements=1)
        test_db.execute("UPDATE items SET status='release' WHERE id=ANY(%s)", (list(members),))
        test_db.commit()
        stage = next(s for s in pinned_stages(test_db, run_id) if s["name"] == STAGE)
        recorder = LockWindowRecorder(test_db)
        materialize_and_gate_deployment_qa_stage(recorder, stage, run_id=run_id)
        windows = _lock_windows(recorder)
        assert len(windows) == size + 1, windows
        widest[size] = max(windows[:-1])
    assert widest[33] == widest[3], widest


def test_an_interrupted_lock_wait_holds_the_stage_instead_of_failing_the_run(
    test_db, monkeypatch
):
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain import db_helpers
    from yoke_core.domain.deploy_pipeline_qa_wait import AWAITING_SCOPED_QA
    from yoke_core.domain.handlers import deployment_qa_stage_relay as relay

    run_id = "run-lock-window-cancelled"
    _seed(test_db, run_id, 17001, 2, requirements=1)
    real_connect = db_helpers.connect

    def bounded_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.execute("SET lock_timeout = '200ms'")
        return conn

    monkeypatch.setattr(db_helpers, "connect", bounded_connect)
    monkeypatch.setattr(relay, "_driven_run", lambda request, function_id: run_id)
    request = FunctionCallRequest(
        function=relay.DISPATCH_FUNCTION_ID,
        actor=ActorContext(actor_id="2", session_id="lock-window-driver"),
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={"stage_name": STAGE},
    )
    holder = real_connect()
    holder.execute("SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,))
    try:
        held = relay.handle_deployment_qa_stage_dispatch(request)
    finally:
        holder.rollback()
        holder.close()
    result = held.result_payload
    assert held.primary_success
    assert result["code"] == AWAITING_SCOPED_QA
    assert result["message"].startswith("qa_stage_dispatch_interrupted:")
    # The run row lock is bounded on its own and refuses by name.
    assert "(run_busy; pid " in result["message"]
    assert f"yoke watch deploy -- {run_id}" in result["message"]
    status = test_db.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert tuple(status) == ("executing", STAGE)
    retried = relay.handle_deployment_qa_stage_dispatch(request).result_payload
    assert not retried["message"].startswith("qa_stage_dispatch_interrupted:")
    assert test_db.execute(
        "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s", (run_id,)
    ).fetchone()[0]


def test_the_gate_holds_the_run_lock_only_for_each_acceptance(test_db):
    """Members' item walks and two passed groups each re-read under their own lock."""
    from runtime.api.domain.deployment_qa_stage_execution_test_support import (
        _complete_case,
    )
    from yoke_core.domain.deployment_qa_plan_groups import run_groups
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        materialize_and_gate_deployment_qa_stage,
    )
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

    run_id = "run-lock-window-accepted"
    members = _seed(test_db, run_id, 18001, 2, requirements=1)
    for member in members:
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
        )
    _form_groups(run_id)(test_db)
    groups = run_groups(test_db, [run_id], STAGE)
    assert len(groups) == 2 and all(group.open for group in groups), groups
    walks = [(member, None) for member in members]
    walks += [(None, group.plan_id) for group in groups]
    for member, plan in walks:
        execution = begin_plan_execution(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
            plan=plan,
            actor_id="2",
            session_id="lock-window-walker",
        )
        _complete_case(test_db, execution)
    stage = next(s for s in pinned_stages(test_db, run_id) if s["name"] == STAGE)
    assert (
        materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=run_id)[0] == 0
    )
    assert all(group.closed for group in run_groups(test_db, [run_id], STAGE))
    recorder = LockWindowRecorder(test_db)
    assert (
        materialize_and_gate_deployment_qa_stage(recorder, stage, run_id=run_id)[0] == 0
    )
    locked = [text for held, text in recorder.statements if held]
    assert locked  # each acceptance is still re-read under the run lock
    assert not any("qa_plan_executions" in text for text in locked), locked
