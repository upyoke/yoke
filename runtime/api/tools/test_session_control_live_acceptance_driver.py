"""Deterministic orchestration tests for Fleet live acceptance."""

from __future__ import annotations

import json
from typing import Any

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceMatrix,
)
from runtime.api.tools.session_control_live_acceptance_driver import (
    LiveAcceptanceDriver,
)


RELEASE_SHA = "a" * 40
SERVER_BUILD = "a" * 12


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += max(seconds, 0.001)


class _ScenarioClient:
    def __init__(
        self,
        cell: AcceptanceCell,
        *,
        registration_missing: bool = False,
        wake_evidence_missing: bool = False,
        malformed_count: bool = False,
    ) -> None:
        self.cell = cell
        self.session_id = cell.session_id or f"{cell.surface}-created-session"
        self.registration_missing = registration_missing
        self.wake_evidence_missing = wake_evidence_missing
        self.malformed_count = malformed_count
        self.calls: list[tuple[list[str], str | None]] = []
        self.create_count = 0
        self.send_counts: dict[str, int] = {}

    def call(self, args, *, stdin: str | None = None) -> dict[str, Any]:
        argv = list(args)
        self.calls.append((argv, stdin))
        if argv[:2] == ["sessions", "list"]:
            return self._roster()
        if argv[:2] == ["sessions", "create"]:
            return self._create(argv)
        if argv[:4] == ["session-control", "launch", "get", "launch-1"]:
            return {"launch": self._launch(terminal=True)}
        if argv[:2] == ["say", "--preview"]:
            return {"recipient_count": 1, "recipients": [self._recipient()]}
        if argv[:2] == ["say", "--stdin"]:
            return self._send(argv)
        if argv[:2] == ["messages", "get"]:
            return self._message(argv[2])
        raise AssertionError(f"unexpected acceptance call: {argv!r}")

    def _recipient(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "executor_surface": self.cell.surface,
            "executor_version": self.cell.expected_version,
            "machine_id": self.cell.machine_id,
            "model": self.cell.model,
        }

    def _roster(self) -> dict[str, Any]:
        return {
            "fields": [],
            "rows": [
                {
                    **self._recipient(),
                    "project": "yoke",
                    "liveness": "active",
                    "turn_posture": "waiting",
                    "messageability": {
                        "wake_operation": "message_stopped",
                        "wake_available": self.cell.wake_supported,
                    },
                }
            ],
        }

    def _launch(self, *, terminal: bool) -> dict[str, Any]:
        registered = None if self.registration_missing else self.session_id
        return {
            "launch_id": "launch-1",
            "message_id": "launch-message",
            "state": "succeeded" if terminal else "queued",
            "result_code": "registered_and_injected" if terminal else None,
            "requested_surface": self.cell.surface,
            "native_session_id": self.session_id if terminal else None,
            "registered_session_id": registered if terminal else None,
        }

    def _create(self, argv: list[str]) -> dict[str, Any]:
        if "--preview" in argv:
            return {
                "launchable": True,
                "selected_relay": {"version": self.cell.expected_version},
            }
        self.create_count += 1
        return {
            "launch": self._launch(terminal=False),
            "deduplicated": self.create_count > 1,
        }

    def _send(self, argv: list[str]) -> dict[str, Any]:
        key = argv[argv.index("--idempotency-key") + 1]
        self.send_counts[key] = self.send_counts.get(key, 0) + 1
        phase = "wake" if key.endswith(":wake") else "initial"
        return {
            "message_id": f"{phase}-message",
            "recipients": [self._recipient()],
            "recipient_count": 1,
            "deduplicated": self.send_counts[key] > 1,
        }

    def _message(self, message_id: str) -> dict[str, Any]:
        wake = message_id == "wake-message"
        supported_wake = wake and self.cell.wake_supported
        pending = wake and not self.cell.wake_supported
        wake_count: Any = 1 if supported_wake else 0
        if supported_wake and self.wake_evidence_missing:
            wake_count = 0
        injection_count: Any = 0 if pending else 1
        if self.malformed_count:
            injection_count = "not-a-count"
        recipient = {
            **self._recipient(),
            "state": "pending" if pending else "acknowledged",
            "injection_count": injection_count,
            "wake_attempt_count": wake_count,
            "acknowledged_at": "" if pending else "2026-08-23T12:00:00Z",
            "last_wake_at": (
                "2026-08-23T12:00:01Z" if supported_wake and wake_count else ""
            ),
        }
        return {
            "message": {
                "message_id": message_id,
                "body": "MUST-NOT-ENTER-REPORT",
                "recipients": [recipient],
            }
        }


def _driver(client: _ScenarioClient) -> LiveAcceptanceDriver:
    clock = _Clock()
    return LiveAcceptanceDriver(client, sleep=clock.sleep, monotonic=clock.monotonic)


def test_create_cell_requires_binding_ack_wait_wake_and_dedupe() -> None:
    cell = AcceptanceCell("codex-desktop", "26.814.41407", "create", model="gpt-5.6")
    client = _ScenarioClient(cell)

    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="release-1",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    assert report["status"] == "passed"
    assert report["registration_identity_matched"] is True
    assert report["initial_message"]["injection_count"] == 1
    assert report["wake_message"]["wake_attempt_count"] == 1
    assert report["initial_deduplicated"] is True
    assert report["wake_deduplicated"] is True
    rendered = json.dumps(report)
    assert "MUST-NOT-ENTER-REPORT" not in rendered
    for argv, body in client.calls:
        if body:
            assert body not in argv
            assert "--stdin" in argv


def test_known_unwakeable_surface_must_remain_pending() -> None:
    cell = AcceptanceCell(
        "claude-desktop",
        "1.32885.1",
        "identify",
        session_id="claude-desktop-session",
    )
    client = _ScenarioClient(cell)

    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="release-2",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    assert report["status"] == "passed"
    assert report["wake_supported"] is False
    assert report["wake_outcome"] == "expected_pending"
    assert report["wake_message"]["state"] == "pending"
    assert report["wake_message"]["wake_attempt_count"] == 0


def test_native_success_without_registration_fails_closed() -> None:
    cell = AcceptanceCell("codex-cli", "0.148.0-alpha.15", "create")
    client = _ScenarioClient(cell, registration_missing=True)

    report = _driver(client).run(
        AcceptanceMatrix("yoke", (cell,)),
        run_id="release-3",
        release_sha=RELEASE_SHA,
        server_build=SERVER_BUILD,
        engine_version="0.1.1+launch.999",
        caller_session_id="main-session",
        timeout_seconds=10,
        poll_seconds=1,
        unsupported_observation_seconds=2,
    )

    assert report["status"] == "failed"
    assert report["cells"][0]["failure_code"] == "launch_registration_missing"


def test_ack_without_wake_receipt_and_malformed_counts_fail_closed() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.238", "create")
    missing = _ScenarioClient(cell, wake_evidence_missing=True)
    malformed = _ScenarioClient(cell, malformed_count=True)

    first = _driver(missing).run(
        AcceptanceMatrix("yoke", (cell,)),
        run_id="release-4",
        release_sha=RELEASE_SHA,
        server_build=SERVER_BUILD,
        engine_version="0.1.1+launch.999",
        caller_session_id="main-session",
        timeout_seconds=10,
        poll_seconds=1,
        unsupported_observation_seconds=2,
    )
    second = _driver(malformed).run(
        AcceptanceMatrix("yoke", (cell,)),
        run_id="release-5",
        release_sha=RELEASE_SHA,
        server_build=SERVER_BUILD,
        engine_version="0.1.1+launch.999",
        caller_session_id="main-session",
        timeout_seconds=10,
        poll_seconds=1,
        unsupported_observation_seconds=2,
    )

    assert first["cells"][0]["failure_code"] == "wake_evidence_missing"
    assert second["cells"][0]["failure_code"] == "receipt_count_invalid"
