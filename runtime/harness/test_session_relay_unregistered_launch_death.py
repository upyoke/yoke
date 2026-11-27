"""The poll that sees a launched native gone reports it before any deadline."""

from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from yoke_contracts.process_ancestry import process_start_time
from yoke_harness import session_launch_handles, session_relay_launch_settlement
from yoke_harness.session_launch_containment import (
    record_supervised_native,
    supervision_record_path,
)
from yoke_harness.session_relay_launch_settlement import (
    report_unregistered_launch_deaths,
    unregistered_launch_deaths,
)
from yoke_harness.session_relay_native_capture_format import compose_capture
from yoke_harness.session_relay_native_diagnostics import native_diagnostic_path
from yoke_harness.session_relay_process_liveness import verified_dead_sessions


LAUNCH_ID = "33333333-3333-4333-8333-333333333333"
REFUSAL = "API 400: model requires a newer CLI version"


class _Inventory:
    relay_id = "relay-1"
    machine_id = "machine-1"
    project_ids = (10,)


class _Dispatcher:
    """Accept one report and answer the way the control plane answers."""

    def __init__(self, *, success: bool = True, result=None) -> None:
        self.success = success
        self.result = {"closed_launches": [LAUNCH_ID]} if result is None else result
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, *, function_id: str, target: Any, payload: Any, timeout_s: int):
        self.payloads.append(dict(payload))
        return type(
            "Response",
            (),
            {"success": self.success, "result": self.result},
        )()


def _supervised(state_dir: Path) -> None:
    record_supervised_native(
        LAUNCH_ID,
        os.getpid(),
        native_session_id="native-session",
        state_dir=state_dir,
    )


def _capture(state_dir: Path) -> None:
    native_diagnostic_path(f"nd-{LAUNCH_ID}", state_dir=state_dir).write_bytes(
        compose_capture(
            stdout=b"turn failed: CursorAcpError: initialize refused\n",
            stderr=f"{REFUSAL}\n".encode(),
            exit_code=1,
            exit_at="2026-09-04T17:31:02Z",
        )
    )


def test_a_gone_native_that_never_registered_is_reported_with_its_capture(
    tmp_path: Path,
) -> None:
    custody = tmp_path / "custody"
    relay = tmp_path / "relay"
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    assert record_supervised_native(
        LAUNCH_ID, process.pid, native_session_id="native-session", state_dir=custody
    )
    process.kill()
    process.wait()
    _capture(relay)
    dispatcher = _Dispatcher()

    reported = report_unregistered_launch_deaths(
        dispatcher,
        _Inventory(),
        state_dir=relay,
        custody_state_dir=custody,
        # A reused pid names a different process, so this native is gone.
        start_time_of=lambda _pid: "some-other-start",
    )

    assert reported == (LAUNCH_ID,)
    launches = dispatcher.payloads[0]["launches"]
    assert [entry["launch_id"] for entry in launches] == [LAUNCH_ID]
    evidence = launches[0]["evidence"]
    assert evidence["native_diagnostic_ref"] == f"nd-{LAUNCH_ID}"
    assert evidence["exit_code"] == 1
    assert evidence["native_stderr_tail"] == REFUSAL
    # The process is gone and the report landed, so nothing re-reports it.
    assert not supervision_record_path(LAUNCH_ID, custody).exists()


def test_a_running_launch_native_is_not_reported_at_all(tmp_path: Path) -> None:
    # The record names this process, which is demonstrably still running.
    record_supervised_native(
        LAUNCH_ID,
        os.getpid(),
        native_session_id="native-session",
        state_dir=tmp_path,
    )
    dispatcher = _Dispatcher()

    assert unregistered_launch_deaths(state_dir=tmp_path) == ()
    assert (
        report_unregistered_launch_deaths(
            dispatcher,
            _Inventory(),
            state_dir=tmp_path,
            custody_state_dir=tmp_path,
        )
        == ()
    )
    assert dispatcher.payloads == []
    assert supervision_record_path(LAUNCH_ID, tmp_path).exists()


def test_fatal_native_capture_reports_before_supervisor_pid_disappears(
    tmp_path: Path,
) -> None:
    custody = tmp_path / "custody"
    relay = tmp_path / "relay"
    _supervised(custody)
    _capture(relay)
    dispatcher = _Dispatcher()

    reported = report_unregistered_launch_deaths(
        dispatcher,
        _Inventory(),
        state_dir=relay,
        custody_state_dir=custody,
        start_time_of=process_start_time,
    )

    assert reported == (LAUNCH_ID,)
    assert (
        dispatcher.payloads[0]["launches"][0]["evidence"]["native_stderr_tail"]
        == REFUSAL
    )
    assert supervision_record_path(LAUNCH_ID, custody).exists()


def test_finalized_bound_capture_is_reported_while_the_session_is_live(tmp_path, monkeypatch):
    handles = tmp_path / "handles"
    handles.mkdir()
    monkeypatch.setattr(session_launch_handles, "native_handle_directory", lambda: handles)
    monkeypatch.setattr(session_relay_launch_settlement, "native_handle_directory", lambda: handles)
    handle = handles / f"{LAUNCH_ID}.json"
    handle.write_text(json.dumps({
        "launch_id": LAUNCH_ID, "pid": 4321, "process_start_time": "start",
        "target_session_id": "bound-session",
    }), encoding="utf-8")
    native_diagnostic_path(f"nd-{LAUNCH_ID}", state_dir=tmp_path).write_bytes(
        compose_capture(stdout=b"", stderr=b"", exit_code=0, exit_at="2026-09-04T17:31:02Z")
    )
    assert verified_dead_sessions(
        state_dir=tmp_path, anchors_dir=tmp_path / "anchors",
        start_time_of=lambda _pid: "start",
    ) == ()

    dispatcher = _Dispatcher(result={"skipped_launches": [{"launch_id": LAUNCH_ID, "status": "registered"}]})
    assert report_unregistered_launch_deaths(
        dispatcher, _Inventory(), state_dir=tmp_path, custody_state_dir=tmp_path,
    ) == (LAUNCH_ID,)
    assert "native_exit_reported" not in json.loads(handle.read_text(encoding="utf-8"))
    dispatcher.result = {"recorded_native_exits": [LAUNCH_ID]}
    assert report_unregistered_launch_deaths(
        dispatcher, _Inventory(), state_dir=tmp_path, custody_state_dir=tmp_path,
    ) == (LAUNCH_ID,)
    assert json.loads(handle.read_text(encoding="utf-8"))["native_exit_reported"] is True
    evidence = dispatcher.payloads[-1]["launches"][0]["evidence"]
    assert evidence["native_exit_at"] == "2026-09-04T17:31:02.000000Z"
    assert evidence["native_pid"] == 4321
    assert evidence["registered_session_id"] == "bound-session"
    assert report_unregistered_launch_deaths(
        dispatcher, _Inventory(), state_dir=tmp_path, custody_state_dir=tmp_path,
    ) == ()
