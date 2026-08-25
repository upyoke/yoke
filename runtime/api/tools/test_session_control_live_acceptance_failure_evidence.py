"""Body-free failure evidence in Fleet acceptance reports."""

from __future__ import annotations

import json

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


def _run(client: _ScenarioClient, cell: AcceptanceCell, run_id: str) -> dict:
    return _driver(client).run(
        AcceptanceMatrix("yoke", (cell,)),
        run_id=run_id,
        release_sha=RELEASE_SHA,
        server_build=SERVER_BUILD,
        engine_version="0.1.1+launch.999",
        caller_session_id="main-session",
        timeout_seconds=3,
        poll_seconds=1,
        unsupported_observation_seconds=2,
    )


class _NoAckClient(_ScenarioClient):
    def simulate_target_tool_hook(self) -> None:
        return None


def test_ack_timeout_retains_the_last_body_free_receipt() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.245", "create")
    report = _run(_NoAckClient(cell), cell, "release-ack-timeout")
    failure = report["cells"][0]

    assert failure["failure_code"] == "ack_timeout"
    assert failure["failure_evidence"] == {
        "message_id": "launch-message",
        "state": "pending",
        "injection_count": 1,
        "wake_attempt_count": 0,
        "acknowledged_at": "",
        "last_wake_at": "",
        "native_wake_attempts": {
            "attempt_count": 0,
            "attempts_truncated": False,
            "attempts": [],
        },
        "native_traffic_body_free": True,
    }
    assert "MUST-NOT-ENTER-REPORT" not in json.dumps(report)


def test_invalid_acknowledged_wake_keeps_attempt_summaries() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.245", "create")
    report = _run(
        _ScenarioClient(cell, duplicate_wake_attempt=True),
        cell,
        "release-invalid-wake",
    )
    failure = report["cells"][0]

    assert failure["failure_code"] == "wake_attempt_count_invalid"
    attempts = failure["failure_evidence"]["native_wake_attempts"]["attempts"]
    assert [attempt["attempt_id"] for attempt in attempts] == [
        "wake-attempt-1",
        "wake-attempt-2",
    ]
    assert all("evidence" not in attempt for attempt in attempts)
    assert "MUST-NOT-ENTER-REPORT" not in json.dumps(report)


def test_ack_without_wake_receipt_and_malformed_counts_fail_closed() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.245", "create")
    missing = _run(
        _ScenarioClient(cell, wake_evidence_missing=True),
        cell,
        "release-missing-wake",
    )
    malformed = _run(
        _ScenarioClient(cell, malformed_count=True),
        cell,
        "release-malformed-count",
    )

    assert missing["cells"][0]["failure_code"] == "wake_evidence_missing"
    assert "failure_evidence" in missing["cells"][0]
    assert malformed["cells"][0]["failure_code"] == "receipt_count_invalid"
