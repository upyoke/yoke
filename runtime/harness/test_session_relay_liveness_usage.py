"""What a dead native measured travels on the report that proves it gone."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.session_identity import ANCHORS_DIR_NAME
from yoke_harness.session_relay_process_liveness import report_verified_dead_sessions
from yoke_harness.session_relay_termination import NATIVE_HANDLE_DIRECTORY_NAME


DEAD_SESSION = "22222222-2222-4222-8222-222222222222"
RECORDED_START = "Mon Aug 24 08:00:00 2026"


class _Inventory:
    relay_id = "machine:test"
    machine_id = "machine-1"
    project_ids = (1,)


class _Response:
    def __init__(self, success: bool, result=None, error=None) -> None:
        self.success = success
        self.result = result
        self.error = error


class _Dispatcher:
    def __init__(self, response: _Response) -> None:
        self.calls: list[dict] = []
        self._response = response

    def __call__(self, *, function_id, target, payload, timeout_s):
        del target, timeout_s
        self.calls.append({"function_id": function_id, **payload})
        return self._response


def _handle(state_dir: Path, session_id: str, pid: int, launch: str) -> None:
    path = state_dir / NATIVE_HANDLE_DIRECTORY_NAME / f"{launch}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "launch_id": launch,
                "target_session_id": session_id,
                "pid": pid,
                "process_start_time": RECORDED_START,
            }
        ),
        encoding="utf-8",
    )


def _start_time_of(live_pids: set[int]):
    def resolve(pid: int) -> str | None:
        return RECORDED_START if pid in live_pids else None

    return resolve


def test_the_reading_the_dead_native_stated_rides_its_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A turn's tokens reach the control plane on the poll that proves it over.

    The reading is attributed by custody: this machine started that native
    for this session, so the tokens its result states are this session's,
    whatever conversation identity the vendor prints inside the result.
    """
    from yoke_cli.config import machine_config
    from yoke_contracts.session_usage_facts import usage_from_document
    from yoke_harness.session_relay_native_capture_format import compose_capture
    from yoke_harness.session_relay_native_diagnostics import (
        diagnostic_reference,
        native_diagnostic_path,
        write_native_capture,
    )
    from runtime.harness.test_cursor_native_result_usage import NATIVE_RESULT_LINE

    home = tmp_path / "yoke-home"
    home.mkdir()
    monkeypatch.setattr(machine_config, "yoke_home", lambda: home)
    launch_id = "44444444-4444-4444-8444-444444444444"
    _handle(tmp_path, DEAD_SESSION, 4002, launch_id)
    write_native_capture(
        native_diagnostic_path(
            diagnostic_reference(launch_id), state_dir=tmp_path, create=True
        ),
        compose_capture(stdout=NATIVE_RESULT_LINE.encode(), stderr=b"", exit_code=0),
    )
    dispatcher = _Dispatcher(_Response(True, {"ended": []}))

    report_verified_dead_sessions(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        anchors_dir=tmp_path / ANCHORS_DIR_NAME,
        start_time_of=_start_time_of(set()),
    )

    reported = dispatcher.calls[0]["sessions"][0]
    assert reported["session_id"] == DEAD_SESSION
    assert usage_from_document(reported["usage_totals"]).billable_tokens() > 0


def test_a_death_with_nothing_measured_carries_no_reading(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from yoke_cli.config import machine_config

    home = tmp_path / "yoke-home"
    home.mkdir()
    monkeypatch.setattr(machine_config, "yoke_home", lambda: home)
    _handle(tmp_path, DEAD_SESSION, 4002, "launch-dead")
    dispatcher = _Dispatcher(_Response(True, {"ended": []}))

    report_verified_dead_sessions(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        anchors_dir=tmp_path / ANCHORS_DIR_NAME,
        start_time_of=_start_time_of(set()),
    )

    assert "usage_totals" not in dispatcher.calls[0]["sessions"][0]
