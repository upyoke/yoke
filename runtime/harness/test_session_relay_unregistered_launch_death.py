"""The poll that sees a launched native gone reports it before any deadline."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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


LAUNCH_ID = "33333333-3333-4333-8333-333333333333"
REFUSAL = "cursor-agent: authentication required"


class _Inventory:
    relay_id = "relay-1"
    machine_id = "machine-1"
    project_ids = (10,)


class _Dispatcher:
    """Accept one report and answer the way the control plane answers."""

    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, *, function_id: str, target: Any, payload: Any, timeout_s: int):
        self.payloads.append(dict(payload))
        return type(
            "Response",
            (),
            {"success": self.success, "result": {"closed_launches": [LAUNCH_ID]}},
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
    _supervised(tmp_path)
    _capture(tmp_path)
    dispatcher = _Dispatcher()

    reported = report_unregistered_launch_deaths(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
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
    assert not supervision_record_path(LAUNCH_ID, tmp_path).exists()


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
        report_unregistered_launch_deaths(dispatcher, _Inventory(), state_dir=tmp_path)
        == ()
    )
    assert dispatcher.payloads == []
    assert supervision_record_path(LAUNCH_ID, tmp_path).exists()
