"""Tests for machine-wide heavy-gate admission control."""

from __future__ import annotations

import threading
import time
import uuid

import psycopg
import pytest

from yoke_core.domain import test_gate_timeout
from yoke_core.tools import gate_admission


def _scratch_lock_base() -> int:
    # Distinct per test so slot scenarios never collide with live gate
    # slots (or each other) on the shared cluster's global lock space.
    return int(uuid.uuid4().int % 1_000_000) + 0x7A000000


def test_is_heavy_invocation_classification(tmp_path):
    test_file = tmp_path / "test_probe.py"
    test_file.write_text("")
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()

    assert gate_admission.is_heavy_invocation([]) is True
    assert gate_admission.is_heavy_invocation(["-k", "expr", "-q"]) is True
    assert gate_admission.is_heavy_invocation([str(suite_dir)]) is True
    assert gate_admission.is_heavy_invocation([str(test_file)]) is False
    assert (
        gate_admission.is_heavy_invocation([f"{test_file}::test_a", "-q"])
        is False
    )
    assert (
        gate_admission.is_heavy_invocation([str(test_file), str(suite_dir)])
        is True
    )


def test_try_acquire_slot_exhaustion_and_crash_release():
    dsn = gate_admission._maintenance_dsn()
    assert dsn is not None
    base = _scratch_lock_base()
    holder = psycopg.connect(dsn, autocommit=True)
    contender = psycopg.connect(dsn, autocommit=True)
    try:
        assert gate_admission.try_acquire_slot(holder, 1, base=base) is True
        assert gate_admission.try_acquire_slot(contender, 1, base=base) is False
        # Session death releases the slot without any explicit unlock —
        # the property that makes crashed gates unable to leak slots.
        holder.close()
        for _ in range(100):
            if gate_admission.try_acquire_slot(contender, 1, base=base):
                break
            time.sleep(0.1)
        else:
            pytest.fail("slot was not released by holder session death")
    finally:
        holder.close()
        contender.close()


def test_two_slots_admit_two_holders():
    dsn = gate_admission._maintenance_dsn()
    assert dsn is not None
    base = _scratch_lock_base()
    first = psycopg.connect(dsn, autocommit=True)
    second = psycopg.connect(dsn, autocommit=True)
    third = psycopg.connect(dsn, autocommit=True)
    try:
        assert gate_admission.try_acquire_slot(first, 2, base=base) is True
        assert gate_admission.try_acquire_slot(second, 2, base=base) is True
        assert gate_admission.try_acquire_slot(third, 2, base=base) is False
    finally:
        first.close()
        second.close()
        third.close()


def test_narrow_invocation_bypasses_admission(tmp_path, monkeypatch):
    test_file = tmp_path / "test_probe.py"
    test_file.write_text("")

    def _fail(*_args, **_kwargs):
        raise AssertionError("narrow invocation must not arbitrate a slot")

    monkeypatch.setattr(gate_admission, "_acquire", _fail)
    with gate_admission.admitted_gate([str(test_file)]):
        pass


def test_descendant_of_admitted_gate_rides_ancestor_slot(monkeypatch):
    monkeypatch.setenv(gate_admission.ADMITTED_ENV, "1")

    def _fail(*_args, **_kwargs):
        raise AssertionError(
            "descendant of an admitted gate must not arbitrate its own slot"
        )

    monkeypatch.setattr(gate_admission, "_acquire", _fail)
    with gate_admission.admitted_gate([]):
        pass


def test_admitted_gate_marks_descendant_environment(monkeypatch):
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    monkeypatch.setattr(gate_admission, "_acquire", lambda _stream: None)
    import os

    with gate_admission.admitted_gate([]):
        assert os.environ.get(gate_admission.ADMITTED_ENV) == "1"
    assert os.environ.get(gate_admission.ADMITTED_ENV) is None


def test_admitted_environment_mirrors_marker(monkeypatch):
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    assert gate_admission.admitted_environment({"A": "1"}) == {"A": "1"}
    monkeypatch.setenv(gate_admission.ADMITTED_ENV, "1")
    assert gate_admission.admitted_environment({"A": "1"}) == {
        "A": "1",
        gate_admission.ADMITTED_ENV: "1",
    }


def test_watch_pytest_mirrors_marker_into_child_env(tmp_path, monkeypatch):
    # The wrapper snapshots the child env before the admission context
    # begins; the marker must still reach the spawned suite, or nested
    # runner invocations inside it deadlock behind their ancestor's slot.
    from yoke_core.tools import watch_pytest

    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    monkeypatch.setattr(gate_admission, "_acquire", lambda _stream: None)
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
    assert captured["env"][gate_admission.ADMITTED_ENV] == "1"


def test_queued_gate_gets_its_whole_budget_once_admitted(tmp_path, monkeypatch):
    # The failure this guards: a gate that queues behind another spends its
    # budget in line and is killed mid-suite, recording a fail verdict for a
    # run that never had time to finish. The budget belongs to execution, so
    # a wait longer than the budget itself must leave the budget intact.
    hold_seconds = 2.0
    budget_seconds = 1
    dsn = gate_admission._maintenance_dsn()
    assert dsn is not None
    base = _scratch_lock_base()
    monkeypatch.setattr(gate_admission, "GATE_SLOT_LOCK_BASE", base)
    monkeypatch.setenv(gate_admission.CAP_ENV, "1")
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    monkeypatch.setenv(
        test_gate_timeout.WATCH_EXECUTION_TIMEOUT_ENV, str(budget_seconds)
    )
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()

    from yoke_core.tools import watch_pytest

    holder = psycopg.connect(dsn, autocommit=True)
    release = threading.Timer(hold_seconds, holder.close)
    observed: dict = {}

    def fake_run_watcher(**kwargs):
        observed["timeout_seconds"] = kwargs["timeout_seconds"]
        observed["waited"] = time.monotonic() - started
        return 0

    monkeypatch.setattr(watch_pytest._watch_runner, "run_watcher", fake_run_watcher)
    try:
        assert gate_admission.try_acquire_slot(holder, 1, base=base) is True
        release.start()
        started = time.monotonic()
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
    finally:
        release.cancel()
        holder.close()

    assert rc == 0
    assert observed["waited"] >= hold_seconds
    assert observed["timeout_seconds"] == budget_seconds


def test_cap_zero_disables_admission(monkeypatch):
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    monkeypatch.setenv(gate_admission.CAP_ENV, "0")

    def _fail(*_args, **_kwargs):
        raise AssertionError("disabled cap must not connect")

    monkeypatch.setattr(gate_admission, "_maintenance_dsn", _fail)
    with gate_admission.admitted_gate([]):
        pass


def test_unreachable_cluster_fails_open(monkeypatch, capsys):
    monkeypatch.delenv(gate_admission.ADMITTED_ENV, raising=False)
    monkeypatch.setenv(gate_admission.CAP_ENV, "3")
    monkeypatch.setattr(gate_admission, "_maintenance_dsn", lambda: None)
    import sys

    with gate_admission.admitted_gate([], stream=sys.stdout):
        pass
    assert "proceeding without a slot" in capsys.readouterr().out


def test_cap_resolution_env_wins(monkeypatch):
    monkeypatch.setenv(gate_admission.CAP_ENV, "7")
    assert gate_admission._resolve_cap() == 7
    monkeypatch.setenv(gate_admission.CAP_ENV, "not-a-number")
    assert (
        gate_admission._resolve_cap()
        >= 0  # falls through to machine config / default without raising
    )
    monkeypatch.delenv(gate_admission.CAP_ENV)
    assert gate_admission._resolve_cap() >= 0
