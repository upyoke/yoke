"""Tests for machine-wide heavy-gate admission control."""

from __future__ import annotations

import time
import uuid

import psycopg
import pytest

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


def test_cap_zero_disables_admission(monkeypatch):
    monkeypatch.setenv(gate_admission.CAP_ENV, "0")

    def _fail(*_args, **_kwargs):
        raise AssertionError("disabled cap must not connect")

    monkeypatch.setattr(gate_admission, "_maintenance_dsn", _fail)
    with gate_admission.admitted_gate([]):
        pass


def test_unreachable_cluster_fails_open(monkeypatch, capsys):
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
