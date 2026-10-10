"""Actual machine file and report clock boundaries retain qualified instants."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import subprocess

import pytest

from yoke_contracts import timestamps
from yoke_cli import hook_latency_benchmark as benchmark
from yoke_cli.commands import universe_ui
from yoke_cli.config import (
    onboard_apply_lock,
    onboard_apply_report,
    onboard_checklist,
    universe_ui_daemon,
    universe_ui_daemon_state,
)
from yoke_cli.local_core import state as core_state

INSTANT = timestamps.parse_instant("2026-10-09T15:00:00.123456Z")
WIRE = "2026-10-09T15:00:00.123456Z"
OPAQUE = "2026-10-09T20:00:00.123456+05:00: arbitrary prose"


@pytest.fixture
def machine(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.setattr(timestamps, "utc_now", lambda: INSTANT)
    return tmp_path


def test_onboarding_lock_formats_before_creating_file(machine, monkeypatch):
    with onboard_apply_lock.acquire(OPAQUE):
        path = onboard_apply_lock.lock_path()
        payload = json.loads(path.read_text())
        assert payload["created_at"] == WIRE
        assert payload["run_id"] == OPAQUE
        assert path.stat().st_mode & 0o777 == 0o600
    assert not path.exists()
    monkeypatch.setattr(timestamps, "utc_now", lambda: datetime(2026, 10, 9))
    with pytest.raises(timestamps.InvalidInstant):
        onboard_apply_lock._open_lock(path, "refused")
    assert not path.exists()


def test_local_core_and_checklist_generate_canonical_clock_without_touching_opaque(
    machine,
):
    path = core_state.save_state({"prose": OPAQUE, "clock_looking_context": WIRE})
    payload = core_state.load_state()
    assert payload["updated_at"] == WIRE
    assert payload["prose"] == OPAQUE
    assert payload["clock_looking_context"] == WIRE
    assert path.stat().st_mode & 0o777 == 0o600
    record = onboard_checklist._new_record("sample")
    assert record["created_at"] == WIRE
    assert record["updated_at"] == WIRE


def test_ui_record_ingress_is_native_and_status_formats_only_at_wire(
    machine, monkeypatch
):
    universe_ui_daemon_state.write_record(
        pid=123, host="localhost", port=456, env=OPAQUE, supervised=False
    )
    record = universe_ui_daemon_state.read_record()
    assert record.started_at == INSTANT
    assert isinstance(record.started_at, datetime)
    path = universe_ui_daemon_state.record_path()
    document = json.loads(path.read_text())
    assert document["started_at"] == WIRE
    document["started_at"] = "2026-10-09T20:00:00.123456+05:00"
    path.write_text(json.dumps(document))
    monkeypatch.setattr(universe_ui_daemon, "process_alive", lambda pid: True)
    monkeypatch.setattr(universe_ui_daemon, "port_accepting", lambda host, port: True)
    assert universe_ui_daemon.status()["started_at"] == WIRE
    assert json.loads(path.read_text())["started_at"] == document["started_at"]
    document["started_at"] = ""
    path.write_text(json.dumps(document))
    with pytest.raises(timestamps.InvalidInstant):
        universe_ui_daemon_state.read_record()


def _preview():
    return {
        "operation": "onboard",
        "mode": "quick",
        "plan": {
            "project": None,
            "steps": [{"action": "create-or-validate-dir", "target": "/tmp/sample"}],
        },
    }


def test_report_producers_and_qualified_resume_preserve_source_bytes(machine):
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(), {"config_path": OPAQUE}
    )
    writer.step_started("create-or-validate-dir", "/tmp/sample")
    writer.step_done("create-or-validate-dir", "/tmp/sample")
    old_bytes = writer.path.read_bytes()
    original = json.loads(old_bytes)
    assert original["created_at"] == original["updated_at"] == WIRE
    assert original["config_path"] == OPAQUE
    assert (
        original["steps"][0]["started_at"]
        == original["steps"][0]["finished_at"]
        == WIRE
    )
    resumed = deepcopy(original)
    resumed["steps"][0]["started_at"] = "2026-10-09T20:00:00.123456+05:00"
    resumed["steps"][0]["finished_at"] = None
    next_writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"resume_payload": resumed, "resume_run_id": "sample-resume"},
    )
    assert next_writer.payload["steps"][0]["started_at"] == WIRE
    assert next_writer.payload["steps"][0]["finished_at"] is None
    assert writer.path.read_bytes() == old_bytes


@pytest.mark.parametrize(
    "bad", ["", "2026-10-09", "2026-10-09T15:00:00", 123, "2026-10-09T15:00:00-00:00"]
)
def test_bad_resume_clock_refuses_before_rewriting_report(machine, bad):
    writer = onboard_apply_report.ApplyReportWriter.start(_preview(), {})
    writer.step_done("create-or-validate-dir", "/tmp/sample")
    before = writer.path.read_bytes()
    payload = deepcopy(writer.payload)
    payload["steps"][0]["started_at"] = bad
    with pytest.raises(timestamps.InvalidInstant):
        onboard_apply_report.ApplyReportWriter.start(
            _preview(),
            {"resume_payload": payload, "resume_run_id": writer.payload["run_id"]},
        )
    assert writer.path.read_bytes() == before


def test_benchmark_formats_native_microsecond_window_and_query(monkeypatch):
    end = timestamps.parse_instant("2026-10-09T20:00:00.123457+05:00")
    instants = iter([INSTANT, end])
    monkeypatch.setattr(benchmark, "utc_now", lambda: next(instants))
    queries = []

    def run(argv, **kwargs):
        if "identity" in argv:
            result = {
                "session_id": "sample",
                "executor": "codex",
                "executor_surface": "codex-cli",
            }
        else:
            result = {"rows": []}
        if "events" in argv:
            queries.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"result": result}), "")

    report = benchmark.run_benchmark(1, run=run)
    assert report["time_window"] == {
        "started_at": WIRE,
        "ended_at": "2026-10-09T15:00:00.123457Z",
    }
    assert queries[0][queries[0].index("--since") + 1] == WIRE
    assert report["phase_coverage"]["missing_phases"]


def test_bad_ui_record_clock_returns_named_cli_refusal(machine, capsys):
    universe_ui_daemon_state.write_record(
        pid=123, host="localhost", port=456, env="sample", supervised=False
    )
    path = universe_ui_daemon_state.record_path()
    document = json.loads(path.read_text())
    document["started_at"] = ""
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    assert universe_ui.ui_status(["--json"]) == 1
    captured = capsys.readouterr()
    assert "invalid_instant" in captured.err
    assert captured.out == ""
    assert path.read_bytes() == before
