"""Environment deferral reporting for the desktop single-writer lock."""

from __future__ import annotations

from typing import Any

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceMatrix,
)
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    RELEASE_SHA,
    SERVER_BUILD,
    _ScenarioClient,
    _driver,
)


class _DesktopWriterLockClient(_ScenarioClient):
    def _roster(self, argv: list[str] | None = None) -> dict[str, Any]:
        result = super()._roster(argv)
        for row in result["rows"]:
            if row["session_id"] == self.session_id:
                row.update(
                    {
                        "liveness": "ended",
                        "mode": "wait",
                        "ended_at": "2026-08-25T18:00:00Z",
                        "claims": [],
                        "current_item": None,
                        "turn_posture": "waiting",
                    }
                )
                row["messageability"].update(
                    {
                        "wake_interface": "supported",
                        "wake_operation": "message_stopped",
                        "wake_available": True,
                    }
                )
        return result


def test_created_codex_desktop_writer_lock_is_an_explicit_deferral() -> None:
    cell = AcceptanceCell("codex-desktop", "26.818.61809", "create")
    client = _DesktopWriterLockClient(cell)

    report = _driver(client).run(
        AcceptanceMatrix("yoke", (cell,)),
        run_id="release-desktop-writer-lock",
        release_sha=RELEASE_SHA,
        server_build=SERVER_BUILD,
        engine_version="0.1.1+launch.999",
        caller_session_id="main-session",
        timeout_seconds=10,
        poll_seconds=1,
        unsupported_observation_seconds=2,
    )

    deferred = report["cells"][0]
    assert report["status"] == "passed"
    assert deferred["status"] == "deferred"
    assert deferred["deferral_code"] == "desktop_single_writer_lock"
    assert deferred["wake_outcome"] == "deferred_environment"
    assert deferred["launch_id"] == "launch-1"
    assert deferred["initial_message"]["state"] == "acknowledged"
    assert deferred["stopped_liveness"] == "ended"
    assert not any(
        argv[:2] == ["say", "--stdin"]
        and argv[argv.index("--idempotency-key") + 1].endswith(":wake")
        for argv, _body in client.calls
    )
