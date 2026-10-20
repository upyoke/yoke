"""Run start and carried enrollment hold the run row only to re-check and write.

Every other writer of a run queues behind its ``deployment_runs`` row lock,
so the reads whose cost grows with the members run before it. These record
the statements a start and an enrollment send, in order, and compare what
runs after the lock statement for a small run and a large one; then they
land a change between the unlocked reads and the lock and prove the locked
path answers from the changed state.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from runtime.api.domain.test_deployment_membership_round_trips import (
    _admit_all,
    _created_run,
    _members,
    _statements,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan
from yoke_core.domain import deployment_run_carried_membership as carried_membership
from yoke_core.domain import deployment_run_start
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members
from yoke_core.domain.deployment_run_unheld_candidates import (
    CandidateCustody,
    CustodyResolution,
)
from yoke_core.domain.schema_read_scope import composition_reads

SMALL, LARGE = 3, 30
_LOCK = "SELECT status FROM deployment_runs WHERE id=%s FOR UPDATE"

#: Readers whose work grows with the members; none may run under the lock.
_MEMBER_READERS = frozenset(
    {
        "read_pinned_items",
        "read_snapshot_inputs",
        "outstanding_post_deploy_requirement_sets",
        "item_completion_flow_facts",
        "needed_member_ids",
        "supplemental_item_ids",
        "carried_membership_refusal",
        "open_landing_refusals",
    }
)


class _Recorder:
    """Forward to ``inner``, keeping each statement's reader in order."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.log: list[tuple[str, str]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def execute(self, sql: str, params: Any = ()) -> Any:
        frame = inspect.currentframe().f_back
        while frame and frame.f_globals.get("__name__", "").endswith(
            ("db_helpers", "db_backend")
        ):
            frame = frame.f_back
        reader = frame.f_code.co_name if frame else "unknown"
        self.log.append((reader, " ".join(str(sql).split())))
        return self._inner.execute(sql, params)

    def after_lock(self) -> list[str]:
        index = next(i for i, (_, sql) in enumerate(self.log) if sql == _LOCK)
        return [reader for reader, _ in self.log[index:]]

    def before_lock(self) -> list[str]:
        index = next(i for i, (_, sql) in enumerate(self.log) if sql == _LOCK)
        return [reader for reader, _ in self.log[:index]]


def _known_carried(item_ids: list[int]) -> dict[str, Any]:
    return {
        "schema": 1,
        "derivation": {"contents_known": True, "reason": "test-fixture"},
        "items": [{"item_id": item_id} for item_id in item_ids],
        "commits": [],
        "bound_projects": [],
    }


def _startable_run(conn: Any, name: str, members: list[int]) -> tuple[str, int]:
    """A created run whose members each carry an attached QA plan."""
    run_id = _created_run(conn, name, members)
    plan = create_smoke_plan(conn, project="yoke", slug=f"smoke-{name}")
    for item_id in members:
        conn.execute(
            "INSERT INTO qa_plan_item_attachments"
            "(item_id,transition_id,qa_phase,plan_id,attached_at) "
            "VALUES (%s,'implemented','post_deploy',%s,%s)",
            (item_id, plan, "2026-09-14T00:00:00Z"),
        )
    conn.commit()
    _statements(conn, _admit_all(run_id, members))
    # What start preparation records and commits before admission.
    record_bound_sources(conn, run_id)
    conn.execute(
        "UPDATE deployment_runs SET carried_work=%s WHERE id=%s",
        (json.dumps(_known_carried([])), run_id),
    )
    conn.commit()
    return run_id, plan


def _start(conn: Any, run_id: str) -> _Recorder:
    recorder = _Recorder(conn)
    with composition_reads():
        assert deployment_run_start._admit(recorder, run_id, None) is None
    conn.commit()
    return recorder


def _snapshots(conn: Any, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT requirement_snapshot FROM deployment_run_items "
        "WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return [json.loads(row["requirement_snapshot"]) for row in rows]


def test_start_holds_the_run_lock_for_the_same_statements_at_any_size(test_db):
    windows = []
    for name, members in (
        ("window-small", _members(9500, SMALL)),
        ("window-large", _members(9600, LARGE)),
    ):
        run_id, plan = _startable_run(test_db, name, members)
        recorder = _start(test_db, run_id)
        locked = recorder.after_lock()
        assert not _MEMBER_READERS & set(locked), locked
        assert "_plan_members" in recorder.before_lock()
        windows.append(locked)
        snapshots = _snapshots(test_db, run_id)
        assert len(snapshots) == len(members)
        assert {entry["plan"]["id"] for s in snapshots for entry in s["plans"]} == {
            plan
        }
        status = test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()
        assert status["status"] == "executing"
    assert windows[0] == windows[1]


def _land_before_the_lock(monkeypatch, module: Any, name: str, change) -> None:
    """Commit-visible *change* lands after the unlocked reads, before the lock."""
    real = getattr(module, name)

    def racing(conn, *args, **kwargs):
        change(conn)
        return real(conn, *args, **kwargs)

    monkeypatch.setattr(module, name, racing)


def test_start_freezes_the_plan_content_changed_before_its_lock(test_db, monkeypatch):
    run_id, plan = _startable_run(test_db, "window-race", _members(9700, SMALL))
    _land_before_the_lock(
        monkeypatch,
        deployment_run_start,
        "lock_run_with_stable_membership",
        lambda conn: conn.execute(
            "UPDATE qa_plans SET name='Renamed before the lock' WHERE id=%s", (plan,)
        ),
    )
    recorder = _start(test_db, run_id)

    # The unlocked snapshot was stale, so the locked freeze derived it again.
    assert "_freeze_members" in recorder.after_lock()
    names = {
        entry["plan"]["name"]
        for s in _snapshots(test_db, run_id)
        for entry in s["plans"]
    }
    assert names == {"Renamed before the lock"}


def test_start_refuses_a_member_cancelled_before_its_lock(test_db, monkeypatch):
    members = _members(9750, SMALL)
    run_id, _plan = _startable_run(test_db, "window-cancel", members)
    _land_before_the_lock(
        monkeypatch,
        deployment_run_start,
        "lock_run_with_stable_membership",
        lambda conn: conn.execute(
            "UPDATE items SET status='cancelled' WHERE id=%s", (members[1],)
        ),
    )
    with composition_reads(), pytest.raises(ValueError):
        deployment_run_start._admit(test_db, run_id, None)
    test_db.rollback()
    status = test_db.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert status["status"] == "created"


def _enroll(conn: Any, run_id: str, carried: list[int]) -> tuple[tuple, _Recorder]:
    recorder = _Recorder(conn)
    custody = CustodyResolution(
        conn, run_id, candidate=CandidateCustody(enrollable=(), held=())
    )
    with composition_reads():
        enrolled = enroll_carried_members(
            recorder, run_id, carried_work=_known_carried(carried), custody=custody
        )
    conn.commit()
    return enrolled, recorder


def _members_of(conn: Any, run_id: str) -> list[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return [int(row["item_id"]) for row in rows]


def test_enrollment_holds_the_run_lock_for_the_same_statements_at_any_size(test_db):
    windows = []
    for name, carried in (
        ("enroll-small", _members(9800, SMALL)),
        ("enroll-large", _members(9850, LARGE)),
    ):
        run_id = _created_run(test_db, name, carried)
        enrolled, recorder = _enroll(test_db, run_id, carried)
        assert len(enrolled) == len(carried)
        assert _members_of(test_db, run_id) == carried
        locked = recorder.after_lock()
        assert not _MEMBER_READERS & set(locked), locked
        windows.append(locked)
    assert windows[0] == windows[1]


def test_enrollment_decides_again_when_a_candidate_changes_before_its_lock(
    test_db, monkeypatch
):
    carried = _members(9900, SMALL)
    run_id = _created_run(test_db, "enroll-race", carried)
    _land_before_the_lock(
        monkeypatch,
        carried_membership,
        "lock_run",
        lambda conn: conn.execute(
            "UPDATE items SET status='cancelled' WHERE id=%s", (carried[0],)
        ),
    )
    enrolled, recorder = _enroll(test_db, run_id, carried)

    assert "read_pinned_items" in recorder.after_lock()
    assert len(enrolled) == len(carried) - 1
    assert _members_of(test_db, run_id) == carried[1:]
