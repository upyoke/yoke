"""Slot-state visibility for machine-wide heavy-gate admission.

A queued gate that only says "waiting" leaves the operator to guess which
of several worktrees is holding the machine. These cover the identity
stamped on each arbitration connection, the occupancy read that the
cluster's own activity view answers, and the announcement built from it.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
import pytest

from yoke_core.tools import gate_admission


def test_slot_identity_names_the_tree_and_the_process(tmp_path, monkeypatch):
    tree = tmp_path / "YOK-1234"
    tree.mkdir()
    monkeypatch.chdir(tree)

    identity = gate_admission.slot_identity()

    assert identity == f"YOK-1234/pid{os.getpid()}"


def test_slot_identity_survives_an_unreadable_working_directory(monkeypatch):
    def _explode() -> Path:
        raise OSError("cwd was removed underneath us")

    monkeypatch.setattr(gate_admission.Path, "cwd", staticmethod(_explode))

    assert gate_admission.slot_identity() == f"unknown/pid{os.getpid()}"


def test_waiting_announcement_names_holders_and_queue_depth():
    message = gate_admission.waiting_announcement(
        1, 42.4, ["YOK-1111/pid7", "YOK-2222/pid9"], 3,
    )

    assert "YOK-1111/pid7, YOK-2222/pid9" in message
    # Three waiters in the view, one of which is this run.
    assert "2 other queued run(s)" in message
    assert "42s so far" in message


def test_waiting_announcement_without_a_queue_or_a_named_holder():
    message = gate_admission.waiting_announcement(1, 5.0, [], 1)

    assert "did not name itself" in message
    assert "other queued run" not in message


def test_occupancy_reads_holders_and_waiters_from_the_cluster():
    dsn = gate_admission._maintenance_dsn()
    if dsn is None:
        pytest.skip("no shared test cluster reachable")
    marker = uuid.uuid4().hex[:8]
    holder = psycopg.connect(dsn, autocommit=True)
    waiter = psycopg.connect(dsn, autocommit=True)
    observer = psycopg.connect(dsn, autocommit=True)
    try:
        gate_admission._stamp_activity(
            holder, gate_admission.SLOT_HELD_APP_PREFIX, f"held-{marker}",
        )
        gate_admission._stamp_activity(
            waiter, gate_admission.SLOT_WAIT_APP_PREFIX, f"wait-{marker}",
        )

        holders, waiting = gate_admission.slot_occupancy(observer)

        assert f"held-{marker}" in holders
        assert waiting >= 1
        assert not any(name.startswith("wait-") for name in holders)
    finally:
        for conn in (holder, waiter, observer):
            conn.close()


def test_occupancy_never_raises_on_a_connection_that_cannot_answer():
    class _Dead:
        def execute(self, *args, **kwargs):
            raise RuntimeError("connection is closed")

    assert gate_admission.slot_occupancy(_Dead()) == ([], 0)


def test_stamp_activity_passes_the_identity_as_a_parameter():
    """A directory name is data; it must never be spliced into SQL."""
    seen: list[tuple] = []

    class _Recorder:
        def execute(self, sql, params=None):
            seen.append((sql, params))

    gate_admission._stamp_activity(
        _Recorder(), gate_admission.SLOT_HELD_APP_PREFIX, "it's/pid1",
    )

    (sql, params), = seen
    assert "set_config" in sql
    assert params == (f"{gate_admission.SLOT_HELD_APP_PREFIX}it's/pid1",)
    assert "it's" not in sql
