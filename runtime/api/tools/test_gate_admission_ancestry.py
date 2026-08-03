"""Inherited admission state, marker propagation, and the wait bound.

Slot arbitration itself lives in the sibling ``test_gate_admission``; this
module covers what a gate publishes to the processes it spawns and how a
descendant behaves on each of the three inherited situations.
"""

from __future__ import annotations

import os
import sys
import time

import psycopg
import pytest

from yoke_core.domain import test_gate_timeout
from yoke_core.tools import gate_admission

from runtime.api.tools.test_gate_admission import _scratch_lock_base


class _FakeSlotConnection:
    def close(self) -> None:
        pass


def test_descendant_of_admitted_gate_rides_ancestor_slot(monkeypatch):
    monkeypatch.setenv(gate_admission.ADMITTED_ENV, gate_admission.MARKER_SLOT_HELD)

    def _fail(*_args, **_kwargs):
        raise AssertionError(
            "descendant of an admitted gate must not arbitrate its own slot"
        )

    monkeypatch.setattr(gate_admission, "_acquire", _fail)
    with gate_admission.admitted_gate([]):
        pass


def test_admitted_gate_publishes_what_it_actually_holds(monkeypatch):
    # A bare presence flag cannot distinguish these two, and the descendant
    # behavior differs between them, so the published value must.
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    monkeypatch.setattr(
        gate_admission, "_acquire", lambda _stream: _FakeSlotConnection()
    )
    with gate_admission.admitted_gate([]):
        assert (
            os.environ.get(gate_admission.ADMITTED_ENV)
            == gate_admission.MARKER_SLOT_HELD
        )
    assert os.environ.get(gate_admission.ADMITTED_ENV) is None

    monkeypatch.setattr(gate_admission, "_acquire", lambda _stream: None)
    with gate_admission.admitted_gate([]):
        assert (
            os.environ.get(gate_admission.ADMITTED_ENV)
            == gate_admission.MARKER_NO_SLOT
        )
    assert os.environ.get(gate_admission.ADMITTED_ENV) is None


def test_ancestor_admission_state_classifies_the_marker(monkeypatch):
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    assert gate_admission.ancestor_admission_state() is None
    monkeypatch.setenv(gate_admission.ADMITTED_ENV, gate_admission.MARKER_NO_SLOT)
    assert gate_admission.ancestor_admission_state() == gate_admission.MARKER_NO_SLOT
    monkeypatch.setenv(gate_admission.ADMITTED_ENV, gate_admission.MARKER_SLOT_HELD)
    assert gate_admission.ancestor_admission_state() == gate_admission.MARKER_SLOT_HELD
    # A marker written by an older build still reads as a held slot, so its
    # descendants keep riding it rather than arbitrating a second time.
    monkeypatch.setenv(gate_admission.ADMITTED_ENV, "1")
    assert gate_admission.ancestor_admission_state() == gate_admission.MARKER_SLOT_HELD


def test_narrow_invocation_publishes_that_it_holds_nothing(tmp_path, monkeypatch):
    # The gap this closes: a file-scoped run holds no slot, and without
    # publishing that fact its heavy descendants cannot tell "my ancestor
    # holds a slot" from "my ancestor holds nothing".
    test_file = tmp_path / "test_probe.py"
    test_file.write_text("")
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    with gate_admission.admitted_gate([str(test_file)]):
        assert (
            os.environ.get(gate_admission.ADMITTED_ENV)
            == gate_admission.MARKER_NO_SLOT
        )
    assert os.environ.get(gate_admission.ADMITTED_ENV) is None


def test_narrow_invocation_never_downgrades_an_inherited_slot(tmp_path, monkeypatch):
    test_file = tmp_path / "test_probe.py"
    test_file.write_text("")
    monkeypatch.setenv(gate_admission.ADMITTED_ENV, gate_admission.MARKER_SLOT_HELD)
    with gate_admission.admitted_gate([str(test_file)]):
        assert (
            os.environ.get(gate_admission.ADMITTED_ENV)
            == gate_admission.MARKER_SLOT_HELD
        )


def test_admitted_environment_mirrors_marker(monkeypatch):
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    assert gate_admission.admitted_environment({"A": "1"}) == {"A": "1"}
    monkeypatch.setenv(gate_admission.ADMITTED_ENV, gate_admission.MARKER_SLOT_HELD)
    assert gate_admission.admitted_environment({"A": "1"}) == {
        "A": "1",
        gate_admission.ADMITTED_ENV: gate_admission.MARKER_SLOT_HELD,
    }


def test_watch_pytest_mirrors_marker_into_child_env(tmp_path, monkeypatch):
    # The wrapper snapshots the child env before the admission context
    # begins; the marker must still reach the spawned suite, or nested
    # runner invocations inside it deadlock behind their ancestor's slot.
    from yoke_core.tools import watch_pytest

    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    monkeypatch.setattr(
        gate_admission, "_acquire", lambda _stream: _FakeSlotConnection()
    )
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    captured = {}

    def fake_run_watcher(**kwargs):
        captured["env"] = kwargs["env"]
        return 0

    monkeypatch.setattr(
        watch_pytest._watch_runner, "run_watcher", fake_run_watcher
    )
    rc = watch_pytest.main(
        [
            "--raw-capture",
            str(tmp_path / "raw.log"),
            "--progress-capture",
            str(tmp_path / "progress.log"),
            "--",
            str(suite_dir),
            "-q",
        ]
    )
    assert rc == 0
    assert (
        captured["env"][gate_admission.ADMITTED_ENV]
        == gate_admission.MARKER_SLOT_HELD
    )


def test_heavy_descendant_of_a_bypassed_ancestor_does_not_queue(
    monkeypatch, capsys
):
    # The wedge shape, driven through the real admission surface: an
    # unrelated holder owns the only slot, and this run's ancestor bypassed
    # admission and holds nothing, so waiting could never be satisfied by
    # anything the ancestor does. Neither `_acquire` nor `try_acquire_slot`
    # is stubbed here — mocking the admission surface away is what let the
    # wedge ship in the first place.
    dsn = gate_admission._maintenance_dsn()
    assert dsn is not None
    base = _scratch_lock_base()
    monkeypatch.setattr(gate_admission, "GATE_SLOT_LOCK_BASE", base)
    monkeypatch.setenv(gate_admission.CAP_ENV, "1")
    monkeypatch.setenv(gate_admission.ADMITTED_ENV, gate_admission.MARKER_NO_SLOT)
    stranger = psycopg.connect(dsn, autocommit=True)
    try:
        assert gate_admission.try_acquire_slot(stranger, 1, base=base) is True
        started = time.monotonic()
        with gate_admission.admitted_gate([], stream=sys.stdout):
            pass
        elapsed = time.monotonic() - started
    finally:
        stranger.close()

    assert elapsed < gate_admission._POLL_INTERVAL_S
    assert "ancestor bypassed admission" in capsys.readouterr().out


def test_wait_bound_expires_and_the_run_proceeds(monkeypatch, capsys):
    # No ancestor, a real stranger on the only slot, and a bound short
    # enough to expire: the run must come back rather than wait for the
    # life of the process.
    dsn = gate_admission._maintenance_dsn()
    assert dsn is not None
    base = _scratch_lock_base()
    monkeypatch.setattr(gate_admission, "GATE_SLOT_LOCK_BASE", base)
    monkeypatch.setenv(gate_admission.CAP_ENV, "1")
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    monkeypatch.setenv(test_gate_timeout.WAIT_TIMEOUT_ENV, "0.5")
    stranger = psycopg.connect(dsn, autocommit=True)
    try:
        assert gate_admission.try_acquire_slot(stranger, 1, base=base) is True
        with gate_admission.admitted_gate([], stream=sys.stdout):
            published = os.environ.get(gate_admission.ADMITTED_ENV)
    finally:
        stranger.close()

    assert "proceeding without one" in capsys.readouterr().out
    assert published == gate_admission.MARKER_NO_SLOT


def test_wait_bound_refuses_a_non_positive_override(monkeypatch):
    # "Wait forever" is the failure this bound removes, so it must not be
    # reachable by setting the knob to zero.
    monkeypatch.setenv(test_gate_timeout.WAIT_TIMEOUT_ENV, "0")
    with pytest.raises(ValueError):
        test_gate_timeout.wait_timeout_seconds()
    monkeypatch.delenv(test_gate_timeout.WAIT_TIMEOUT_ENV)
    assert (
        test_gate_timeout.wait_timeout_seconds()
        == test_gate_timeout.DEFAULT_WAIT_TIMEOUT_S
    )
