"""Tests for the apply_patch smoke HC bundle.

Covers HC-apply-patch-deny-smoke and HC-apply-patch-observe-smoke. Each HC is
exercised on its happy path and at least one drift/failure path. Split out of
``test_doctor_hc_codex_hooks`` so the apply-patch module stays cohesive.
"""

from __future__ import annotations

import subprocess

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines import doctor_hc_apply_patch as mod
from yoke_core.engines.doctor_hc_apply_patch import (
    hc_apply_patch_deny_smoke,
    hc_apply_patch_observe_smoke,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _record(fn, conn) -> RecordCollector:
    rec = RecordCollector()
    fn(conn, DoctorArgs(), rec)
    return rec


# ---------------------------------------------------------------------------
# HC-apply-patch-deny-smoke
# ---------------------------------------------------------------------------


def test_deny_smoke_pass_when_module_absent(monkeypatch, conn):
    monkeypatch.setattr(mod, "_smoke_module_available", lambda: False)
    rec = _record(hc_apply_patch_deny_smoke, conn)
    assert rec.results[0].result == "PASS"
    assert "not yet provisioned" in rec.results[0].detail


def test_deny_smoke_pass_on_zero_exit(monkeypatch, conn):
    monkeypatch.setattr(mod, "_smoke_module_available", lambda: True)

    def ok_run(*a, **kw):
        return subprocess.CompletedProcess(args=a, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", ok_run)
    rec = _record(hc_apply_patch_deny_smoke, conn)
    assert rec.results[0].result == "PASS"


def test_deny_smoke_fail_on_nonzero_exit(monkeypatch, conn):
    monkeypatch.setattr(mod, "_smoke_module_available", lambda: True)

    def fail_run(*a, **kw):
        return subprocess.CompletedProcess(
            args=a, returncode=2, stdout="", stderr="boom",
        )

    monkeypatch.setattr(subprocess, "run", fail_run)
    rec = _record(hc_apply_patch_deny_smoke, conn)
    assert rec.results[0].result == "FAIL"
    assert "exited 2" in rec.results[0].detail


# ---------------------------------------------------------------------------
# HC-apply-patch-observe-smoke
# ---------------------------------------------------------------------------


def test_observe_smoke_pass_when_module_absent(monkeypatch, conn):
    monkeypatch.setattr(mod, "_smoke_module_available", lambda: False)
    rec = _record(hc_apply_patch_observe_smoke, conn)
    assert rec.results[0].result == "PASS"


def test_observe_smoke_pass_when_no_events_yet(monkeypatch, conn):
    monkeypatch.setattr(mod, "_smoke_module_available", lambda: True)
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE events (event_name TEXT, envelope TEXT);
        """,
    )
    rec = _record(hc_apply_patch_observe_smoke, conn)
    assert rec.results[0].result == "PASS"
    assert "no apply_patch events" in rec.results[0].detail


def test_observe_smoke_pass_when_events_seen(monkeypatch, conn):
    monkeypatch.setattr(mod, "_smoke_module_available", lambda: True)
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE events (event_name TEXT, envelope TEXT);
        INSERT INTO events VALUES ('HarnessToolCall', '{"tool":"apply_patch"}');
        """,
    )
    rec = _record(hc_apply_patch_observe_smoke, conn)
    assert rec.results[0].result == "PASS"
    assert "apply_patch event" in rec.results[0].detail
