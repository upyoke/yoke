"""Run success and takeover read before the run row lock and hold it only to write.

Each command runs at two run sizes. Reads that grow with the run's members,
and commit comparisons on the repository host, happen before the
``deployment_runs`` row lock; the lock covers a constant re-check and the
writes, so the statements issued while it is held are the same at 3 members
and at 30. A change committed between the read and the lock is read again.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover_case
from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_no_obligation_member_close_out import (
    _no_obligation,
    _ready_member,
)
from runtime.api.domain.test_run_success_member_settlement import (
    REASON,
    _executing_run,
    _run,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    record_case_verdict,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain import deployment_run_candidate_containment as containment
from yoke_core.domain import deployment_run_settle_success as success
from yoke_core.domain import deployment_runs_crud_mutate as mutate
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_target_takeover import (
    NOT_CONTAINED_CODE,
    TakeoverRefused,
    take_over_waiting_run,
)
from yoke_core.domain.schema_read_scope import composition_reads

SIZES = (3, 30)
OLD_LINEAGE = "b" * 40
MOVED_LINEAGE = "e" * 40


class RunLockRecorder:
    """Record statements in order, marking where a run row lock is held.

    ``FOR UPDATE`` on ``deployment_runs`` and an ``UPDATE deployment_runs``
    both start the window, because an update holds the row it wrote until the
    transaction ends; commit and rollback end it.
    """

    def __init__(self, inner: Any) -> None:
        self._conn = inner
        self.statements: list[tuple[bool, str]] = []
        self._locked = False

    def execute(self, sql, *args, **kwargs):
        text = " ".join(str(sql).split())
        if text.startswith("UPDATE deployment_runs ") or (
            "FROM deployment_runs WHERE id=%s" in text and "FOR UPDATE" in text
        ):
            self._locked = True
        self.statements.append((self._locked, text))
        return self._conn.execute(sql, *args, **kwargs)

    def commit(self):
        self._locked = False
        return self._conn.commit()

    def rollback(self):
        self._locked = False
        return self._conn.rollback()

    def close(self):
        """The command closes its connection; the test keeps reading it."""

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def windows(self) -> list[int]:
        """How many statements each run-lock window issued, in order."""
        found, current = [], 0
        for locked, _text in [*self.statements, (False, "")]:
            if locked:
                current += 1
            elif current:
                found.append(current)
                current = 0
        return found

    def locked(self) -> list[str]:
        """The statements issued while a run row lock was held."""
        return [text for held, text in self.statements if held]


def _ready_run(conn: Any, run_id: str, first: int, size: int) -> tuple[int, ...]:
    members = tuple(range(first, first + size))
    for item_id in members:
        _ready_member(conn, item_id, f"sess-settle-{item_id}")
        _no_obligation(conn, item_id, reason=REASON)
    _executing_run(conn, run_id, members)
    return members


def _succeed(conn: Any, monkeypatch, run_id: str) -> RunLockRecorder:
    recorder = RunLockRecorder(conn)
    monkeypatch.setattr(mutate, "connect", lambda _path=None: recorder)
    assert mutate.cmd_update(run_id, "status", "succeeded") is None
    return recorder


def test_run_success_holds_the_run_lock_for_the_same_statements_at_any_size(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    windows = {}
    for size, first in zip(SIZES, (9601, 9701)):
        run_id = f"run-settle-window-{size}"
        members = _ready_run(test_db, run_id, first, size)
        recorder = _succeed(test_db, monkeypatch, run_id)
        windows[size] = recorder.windows()
        assert _run(test_db, run_id) == ("succeeded", True)
        assert {_status(test_db, item_id) for item_id in members} == {"done"}
        # No member is asked one at a time while the run row is held.
        assert not any("item_id=%s" in text for text in recorder.locked())
    assert windows[30] == windows[3], windows


def _deliveries(conn: Any, item_id: int, run_id: str) -> set[str]:
    row = conn.execute(
        "SELECT facts FROM item_gate_satisfactions WHERE item_id=%s "
        "AND obligation='delivery_evidence'",
        (item_id,),
    ).fetchone()
    entries = json.loads(row["facts"]).get("completed_deliveries", [])
    return {e["candidate"] for e in entries if e["run_id"] == run_id}


def test_a_lineage_committed_between_the_success_read_and_the_lock_is_honoured(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    run_id = "run-settle-window-moved"
    [member] = _ready_run(test_db, run_id, 9591, 1)
    reads = []
    real = success._attributions

    def attributions(conn, asked):
        answer = real(conn, asked)
        if not reads:
            # Committed after the unlocked read, before the run row lock.
            test_db.execute(
                "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s",
                (MOVED_LINEAGE, run_id),
            )
            test_db.commit()
        reads.append({e["candidate"] for e in answer.values() if e})
        return answer

    monkeypatch.setattr(success, "_attributions", attributions)
    _succeed(test_db, monkeypatch, run_id)

    assert reads == [{"a" * 40}, {MOVED_LINEAGE}]  # stale, then re-read locked
    assert MOVED_LINEAGE in _deliveries(test_db, member, run_id)


def _waiting_old_run(
    conn: Any, old: str, first: int, size: int, *, closed: int = 1
) -> None:
    """OLD stands on item QA: ``closed`` members closed there, ``size`` waiting."""
    plan = create_smoke_plan(conn, project="yoke", slug=f"smoke-{old}")
    members = tuple(range(first, first + size + closed))
    seed_run_standing_on_qa_stage(
        conn,
        run_id=old,
        project="yoke",
        stages=item_qa_stage_definitions(plan),
        members=members,
        lineage=OLD_LINEAGE,
    )
    conn.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id=ANY(%s)",
        (f"flow-{old}", list(members)),
    )
    for member in members:
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=old,
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=member,
        )
    conn.commit()
    for member in members[:closed]:
        passed = takeover_case._requirement(conn, old, ITEM_QA_STAGE, member)
        record_case_verdict(conn, passed, "pass", evidence=True)
    conn.execute(
        "UPDATE items SET status='done' WHERE id=ANY(%s)", (list(members[:closed]),)
    )
    conn.commit()


def _new_run(conn: Any, new: str, old: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,"
        "target_environment_id,release_lineage,status,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,"
        "'created',created_at FROM deployment_runs WHERE id=%s",
        (new, "c" * 40, old),
    )
    conn.commit()


def _take_over(conn: Any, new: str) -> Any:
    # Creation runs the takeover inside one composition read scope.
    with composition_reads():
        return take_over_waiting_run(conn, new, session_id=DRIVER_SESSION, actor_id=1)


def test_takeover_holds_the_older_run_lock_for_the_same_statements_at_any_size(
    test_db: Any, monkeypatch
) -> None:
    windows, compared_locked = {}, []
    for size, first in zip(SIZES, (9801, 9901)):
        old, new = f"run-takeover-window-old-{size}", f"run-takeover-window-new-{size}"
        _waiting_old_run(test_db, old, first, size)
        _new_run(test_db, new, old)
        recorder = RunLockRecorder(test_db)

        def contains(*_args, _recorder=recorder, **_kwargs):
            compared_locked.append(_recorder._locked)
            return containment.ContainmentVerdict(containment.CONTAINED)

        monkeypatch.setattr(containment, "candidate_contains_commit", contains)
        assert _take_over(recorder, new) == old
        recorder.commit()
        assert len(takeover_case._members(test_db, new)) == size
        assert _run(test_db, old)[0] == "succeeded"
        windows[size] = recorder.windows()
    # The repository comparison ran before the older run's lock, every time.
    assert compared_locked == [False, False]
    assert windows[30] == windows[3], windows


def test_a_lineage_committed_between_the_takeover_read_and_the_lock_is_judged(
    test_db: Any, monkeypatch
) -> None:
    old, new = "run-takeover-window-old-moved", "run-takeover-window-new-moved"
    _waiting_old_run(test_db, old, 9581, 1)
    _new_run(test_db, new, old)
    judged = []

    def contains(_conn, _project_id, *, candidate_lineage, commit_sha):
        judged.append(commit_sha)
        if len(judged) == 1:
            # Committed after the unlocked comparison, before the run lock.
            with connect_test_database(test_db.info.dbname) as writer:
                writer.execute(
                    "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s",
                    (MOVED_LINEAGE, old),
                )
        if commit_sha == OLD_LINEAGE:
            return containment.ContainmentVerdict(containment.CONTAINED)
        return containment.ContainmentVerdict(containment.NOT_CONTAINED, "why")

    monkeypatch.setattr(containment, "candidate_contains_commit", contains)
    with pytest.raises(TakeoverRefused) as refused:
        _take_over(test_db, new)
    test_db.rollback()

    assert judged == [OLD_LINEAGE]
    assert "takeover_inputs_changed" in str(refused.value)
    assert takeover_case._members(test_db, new) == set()
    # A fresh attempt compares the changed lineage before acquiring the lock.
    with pytest.raises(TakeoverRefused) as refused:
        _take_over(test_db, new)
    test_db.rollback()
    assert judged == [OLD_LINEAGE, MOVED_LINEAGE]
    assert NOT_CONTAINED_CODE in str(refused.value)
    assert MOVED_LINEAGE in str(refused.value)
    assert _run(test_db, old)[0] == "executing"


def test_a_takeover_settles_closed_members_in_the_same_statements_at_any_size(
    test_db: Any, monkeypatch
) -> None:
    """The members the older run closed are stamped and attributed as one set."""
    takeover_case._contains(monkeypatch)
    windows = {}
    for size, first in zip(SIZES, (9401, 9501)):
        old, new = f"run-takeover-closed-old-{size}", f"run-takeover-closed-new-{size}"
        _waiting_old_run(test_db, old, first, 1, closed=size)
        _new_run(test_db, new, old)
        recorder = RunLockRecorder(test_db)
        assert _take_over(recorder, new) == old
        recorder.commit()
        assert _run(test_db, old)[0] == "succeeded"
        closed = range(first, first + size)
        assert takeover_case._members(test_db, old) == set(closed)
        stamped = test_db.execute(
            "SELECT DISTINCT deploy_stage FROM items WHERE id=ANY(%s)", (list(closed),)
        ).fetchall()
        assert [row["deploy_stage"] for row in stamped] == ["complete"]
        assert all(_deliveries(test_db, item_id, old) for item_id in closed)
        windows[size] = recorder.windows()
        assert not any("item_id=%s" in text for text in recorder.locked())
    assert windows[30] == windows[3], windows
