"""Doctor uses live listener evidence, independently of warning suppression."""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path

import pytest

from yoke_cli.hook_resident_client import ResidentPaths
from yoke_core.engines import doctor_hc_hook_resident as resident_hc
from yoke_core.engines.doctor_applicability_declarations import (
    DECLARATIONS,
    local_runtime_slugs,
)
from yoke_core.engines.doctor_registry_harness import HARNESS_HEALTH_CHECKS
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_https_local_scope import requested_local_machine_slugs


@pytest.fixture
def paths(monkeypatch, tmp_path):
    # pytest's per-test directory exceeds macOS's Unix socket path limit.
    with tempfile.TemporaryDirectory(prefix="hr-", dir="/tmp") as short_dir:
        paths = ResidentPaths(
            tmp_path,
            Path(short_dir) / "e.sock",
            tmp_path / "lock",
            tmp_path / "log",
        )
        monkeypatch.setattr(resident_hc, "resident_paths", lambda: paths)
        yield paths


def _run():
    rec = RecordCollector()
    resident_hc.hc_hook_resident(None, DoctorArgs(), rec)
    return rec.results[0]


def test_doctor_reports_down_even_with_suppressed_warning(paths):
    (paths.state_dir / "fallback-warning").write_text("9999999999", encoding="utf-8")
    result = _run()
    assert result.check_id == resident_hc.SLUG
    assert result.result == "WARN"
    assert "YOKE_HOOK_RESIDENT_UNREACHABLE" in result.detail
    assert "canonical in-process fallback" in result.detail
    assert str(paths.log) in result.detail
    assert "next hook invocation retries" in result.detail
    assert not paths.socket.exists()  # Doctor must not start a resident.


def test_doctor_reports_stale_socket_as_down(paths):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(paths.socket))
    assert paths.socket.exists()
    assert _run().result == "WARN"


def test_doctor_reports_listener_accepting_connections(paths):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(paths.socket))
        listener.listen()
        result = _run()
    assert result.result == "PASS"
    assert "accepts connections" in result.detail


def test_doctor_reports_unreadable_state(monkeypatch):
    def refuse():
        raise PermissionError("cache inaccessible")

    monkeypatch.setattr(resident_hc, "resident_paths", refuse)
    result = _run()
    assert result.result == "WARN"
    assert "YOKE_HOOK_RESIDENT_STATE_UNREADABLE" in result.detail
    assert "permissions" in result.detail


def test_resident_check_is_registered_for_machine_local_execution():
    assert any(
        check.fn is resident_hc.hc_hook_resident for check in HARNESS_HEALTH_CHECKS
    )
    assert resident_hc.SLUG in local_runtime_slugs()
    shape = DECLARATIONS[resident_hc.SLUG]
    assert shape.project_scope == "any"
    assert shape.runtimes == frozenset({"local"})
    local, source = requested_local_machine_slugs({"only": resident_hc.SLUG})
    assert local == [resident_hc.SLUG]
    assert not source
