"""Quiet-period diagnosis and nested-admission abort decisions."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from yoke_core.domain import process_group_reaping
from yoke_core.tools import _watch_runner, gate_stall_report
from yoke_core.tools._watch_throttle import Classification, LineClass


def test_pid_from_slot_identity_parses_the_suffix():
    assert gate_stall_report.pid_from_slot_identity("YOK-1/pid42") == 42
    assert gate_stall_report.pid_from_slot_identity("no-pid-here") is None


def test_nested_admission_deadlock_is_named_and_aborts(monkeypatch):
    monkeypatch.delenv(gate_stall_report.STALL_ABORT_ENV, raising=False)
    report = gate_stall_report.diagnose_quiet_run(
        root_pid=100,
        holders=["lane/pid50"],
        waiters=["lane/pid200"],
        descendants=[200, 201],
        ancestors=[50, 1],
    )
    assert report.reason == gate_stall_report.NESTED_ADMISSION_DEADLOCK
    assert report.abort is True
    assert "admission slot held by this run's own tree" in report.waiting_on
    assert "pid50" in report.detail and "pid200" in report.detail
    line = report.abort_line(kind="pytest")
    assert "aborted: nested_admission_deadlock" in line
    assert "child process group reaped" in line


def test_stall_abort_can_be_disabled_for_fixtures(monkeypatch):
    monkeypatch.setenv(gate_stall_report.STALL_ABORT_ENV, "0")
    report = gate_stall_report.diagnose_quiet_run(
        root_pid=100,
        holders=["lane/pid100"],
        waiters=["lane/pid200"],
        descendants=[200],
        ancestors=[],
    )
    assert report.reason == gate_stall_report.NESTED_ADMISSION_DEADLOCK
    assert report.abort is False


def test_nested_waiter_behind_a_peer_is_diagnosed_without_abort():
    report = gate_stall_report.diagnose_quiet_run(
        root_pid=100,
        holders=["other/pid9"],
        waiters=["lane/pid200"],
        descendants=[200],
        ancestors=[1],
    )
    assert report.abort is False
    assert report.reason is None
    assert report.waiting_on == "admission slot"
    assert "nested_waiter=lane/pid200" in report.detail


def test_live_child_without_slot_context_names_the_process():
    report = gate_stall_report.diagnose_quiet_run(
        root_pid=100,
        holders=[],
        waiters=[],
        descendants=[300],
        ancestors=[],
    )
    assert report.waiting_on == "child process"
    assert "pid=300" in report.detail
    assert report.abort is False


def test_deploy_watcher_does_not_attribute_concurrent_unrelated_process(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv(_watch_runner.QUIET_HEARTBEAT_SECONDS_ENV, "0.05")
    monkeypatch.setenv(gate_stall_report.STALL_ABORT_ENV, "0")
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    unrelated = process_group_reaping.popen_in_process_group(command)
    out = io.StringIO()
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    try:
        rc = _watch_runner.run_watcher(
            argv=[sys.executable, "-c", "import time; time.sleep(0.25)"],
            classifier=lambda _line: Classification(LineClass.NOISE),
            raw_capture=raw,
            progress_capture=progress,
            kind="deploy",
            stdout_stream=out,
        )
    finally:
        process_group_reaping.terminate_process_group(unrelated)

    assert rc == 0
    text = progress.read_text(encoding="utf-8")
    assert "watch_deploy still running; waiting on: no attributable child" in text
    assert str(unrelated.pid) not in text


def test_quiet_watcher_emits_waiting_on_and_preserves_capture(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv(_watch_runner.QUIET_HEARTBEAT_SECONDS_ENV, "0.05")
    monkeypatch.setenv(gate_stall_report.STALL_ABORT_ENV, "0")

    def fake_diagnose(_root_pid: int):
        return gate_stall_report.StallReport(
            waiting_on="child process",
            detail="pid=999 cmd=sleep",
        )

    monkeypatch.setattr(gate_stall_report, "diagnose_quiet_run", fake_diagnose)

    out = io.StringIO()
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    rc = _watch_runner.run_watcher(
        argv=[sys.executable, "-c", "import time; time.sleep(0.25)"],
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=raw,
        progress_capture=progress,
        kind="pytest",
        stdout_stream=out,
    )
    assert rc == 0
    text = progress.read_text(encoding="utf-8")
    assert "waiting on: child process" in text
    assert "pid=999" in text


def test_quiet_watcher_aborts_nested_admission_deadlock(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv(_watch_runner.QUIET_HEARTBEAT_SECONDS_ENV, "0.05")
    monkeypatch.delenv(gate_stall_report.STALL_ABORT_ENV, raising=False)

    def fake_diagnose(_root_pid: int):
        return gate_stall_report.StallReport(
            waiting_on="admission slot held by this run's own tree",
            reason=gate_stall_report.NESTED_ADMISSION_DEADLOCK,
            abort=True,
            detail="holder=lane/pid1; nested_waiter=lane/pid2",
        )

    monkeypatch.setattr(gate_stall_report, "diagnose_quiet_run", fake_diagnose)

    out = io.StringIO()
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    rc = _watch_runner.run_watcher(
        argv=[sys.executable, "-c", "import time; time.sleep(30)"],
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=raw,
        progress_capture=progress,
        kind="pytest",
        stdout_stream=out,
    )
    assert rc == _watch_runner.STALL_ABORT_EXIT
    raw_text = raw.read_text(encoding="utf-8")
    progress_text = progress.read_text(encoding="utf-8")
    assert "aborted: nested_admission_deadlock" in raw_text
    assert "aborted: nested_admission_deadlock" in progress_text
    assert f"exit={_watch_runner.STALL_ABORT_EXIT}" in progress_text
