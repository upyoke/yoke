"""Deployment QA writers read before the run row lock and hold it only to write.

On a 33-member run, one member's materialize and rematerialize once held the
``deployment_runs`` row lock for minutes while they re-derived every
member's plan groups one query at a time, and every other writer queued
behind them. These runs share one shape at two sizes: every statement count
must be the same at 3 members and at 33, inside and outside the lock.
"""

from __future__ import annotations

from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
)
from runtime.api.domain.test_deployment_qa_shared_plans import _attach
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

STAGE = "item-qa"
SIZES = (("run-lock-window-small", 13001, 3), ("run-lock-window-large", 14001, 33))
_RUN_LOCKS = (
    "FROM deployment_runs WHERE id=%s FOR UPDATE",
    "FROM deployment_runs WHERE id=%s ORDER BY",
)


class LockWindowRecorder:
    """Record statements in order, marking where the run row lock is held."""

    def __init__(self, inner):
        self._conn = inner
        self.statements: list[tuple[bool, str]] = []
        self._locked = False

    def execute(self, sql, *args, **kwargs):
        text = " ".join(str(sql).split())
        if "deployment_runs WHERE id=%s" in text and text.endswith("FOR UPDATE"):
            self._locked = True
        self.statements.append((self._locked, text))
        return self._conn.execute(sql, *args, **kwargs)

    def commit(self):
        self._locked = False
        return self._conn.commit()

    def rollback(self):
        self._locked = False
        return self._conn.rollback()

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def counts(self) -> tuple[int, int]:
        """All statements, and those issued while the run row was locked."""
        return len(self.statements), sum(locked for locked, _ in self.statements)


def _seed(conn, run_id, first_member, members, requirements=10):
    """Two plans every member attaches, plus admitted method cases each."""
    plans = [_plan(conn, f"{run_id}-shared-{n}") for n in range(2)]
    stages = _stages(plans[0])
    stages[1].pop("cases")
    member_ids = tuple(range(first_member, first_member + members))
    _seed_run(conn, run_id=run_id, stages=stages, members=member_ids)
    for member in member_ids:
        ids = tuple(
            _original_requirement(conn, item_id=member, method_id="command")
            for _ in range(requirements)
        )
        snapshot = snapshot_member_requirements(
            conn,
            run_id=run_id,
            item_id=member,
            selection_json=requirement_selection(requirement_ids=ids),
        )
        conn.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=%s "
            "WHERE run_id=%s AND item_id=%s",
            (snapshot, run_id, member),
        )
        for plan in plans:
            _attach(conn, member, plan)
    conn.commit()
    return member_ids


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


def test_member_writes_cost_the_same_at_any_run_size(test_db):
    measured = {}
    for run_id, first, size in SIZES:
        members = _seed(test_db, run_id, first, size)
        measured[size] = {
            "first": _measure(test_db, _materialize(run_id, members[0])),
            "repeat": _measure(test_db, _materialize(run_id, members[0])),
            "peer": _measure(test_db, _materialize(run_id, members[1])),
            "refresh": _measure(
                test_db,
                lambda conn: rematerialize_for_deployment_stage(
                    conn,
                    deployment_run_id=run_id,
                    deployment_stage=STAGE,
                    deployment_member_item_id=members[0],
                ),
            ),
        }
    small, large = measured[3], measured[33]
    assert large == small, f"statement counts grew with members: {measured}"
    for total, locked in large.values():
        # Most of the work is the unlocked read; the lock covers the writes.
        assert locked < total


def test_a_membership_change_during_the_read_is_read_again(test_db, monkeypatch):
    """A peer leaving between the read and the lock is read again, unshared."""
    from yoke_core.domain import deployment_qa_materialization_projection as module
    from yoke_core.domain.deployment_qa_plan_groups import attached_plans
    from yoke_core.domain.deployment_run_member_removal import remove_members_on

    run_id = "run-lock-window-moved"
    first, peer = _seed(test_db, run_id, 15001, 2, requirements=1)
    reads = []
    real = module.MaterializationProjection.__init__

    def read(self, conn, run):
        real(self, conn, run)
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
    assert all(members == [first] for members in attached_plans(test_db, run_id).values())


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
        # Still owing its item QA, so the guard lets it leave the run.
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


def test_a_dispatch_writes_its_cohort_under_one_run_lock(test_db):
    """One lock and one fingerprint check per dispatch, never one per member.

    Under the lock each member costs only its own writes, so the window grows
    by the same few statements per member and holds no run-wide read.
    """
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        materialize_and_gate_deployment_qa_stage,
    )

    widest = {}
    for run_id, first, size in SIZES:
        _seed(test_db, run_id, first, size, requirements=1)
        stage = next(s for s in pinned_stages(test_db, run_id) if s["name"] == STAGE)
        recorder = LockWindowRecorder(test_db)
        materialize_and_gate_deployment_qa_stage(recorder, stage, run_id=run_id)
        windows = _lock_windows(recorder)
        assert len(windows) == 1, windows
        locked = [text for held, text in recorder.statements if held]
        assert sum(text.startswith("SELECT md5(") for text in locked) <= 1
        assert sum(text.endswith("FOR UPDATE") for text in locked) == 1
        widest[size] = windows[0]
    per_member = (widest[33] - widest[3]) / 30
    assert per_member <= 20, widest
    assert widest[3] >= 3 * per_member, widest


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
    """A member answered by two passed groups re-reads each under its own lock."""
    from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        materialize_and_gate_deployment_qa_stage,
    )
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

    run_id = "run-lock-window-accepted"
    members = _seed(test_db, run_id, 18001, 2, requirements=0)
    for member in members:
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
        )
    for _group in range(2):
        execution = begin_plan_execution(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=members[0],
            actor_id="2",
            session_id="lock-window-walker",
        )
        _complete_case(test_db, execution)
    stage = next(s for s in pinned_stages(test_db, run_id) if s["name"] == STAGE)
    assert (
        materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=run_id)[0] == 0
    )
    recorder = LockWindowRecorder(test_db)
    assert (
        materialize_and_gate_deployment_qa_stage(recorder, stage, run_id=run_id)[0] == 0
    )
    locked = [text for held, text in recorder.statements if held]
    assert locked  # each acceptance is still re-read under the run lock
    assert not any("qa_plan_executions" in text for text in locked), locked
