"""Just-in-time grant timing around the exact private wake operation."""

from __future__ import annotations

from runtime.api.tools.session_control_live_acceptance_contract import AcceptanceCell
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
    _driver,
)


class _Qualification:
    def __init__(self, client: _ScenarioClient) -> None:
        self.client = client
        self.events: list[tuple[str, str, int]] = []

    def open(self, _cell: AcceptanceCell, operation: str):
        self.events.append(("open", operation, len(self.client.calls)))
        return operation if operation == "message_stopped" else None

    def verify(self, grant) -> None:
        self.events.append(("verify", str(grant or "none"), len(self.client.calls)))


def test_stopped_grant_opens_just_before_wake_and_verifies_after_ack() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.241", "create")
    client = _ScenarioClient(cell)
    qualification = _Qualification(client)

    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="stage-proof-jit",
        timeout=10,
        poll=1,
        unsupported_observation=2,
        qualification=qualification,
    )

    assert report["status"] == "passed"
    assert [event[:2] for event in qualification.events] == [
        ("open", "message_stopped"),
        ("verify", "message_stopped"),
    ]
    open_call_count = qualification.events[0][2]
    verify_call_count = qualification.events[1][2]
    before_open = client.calls[:open_call_count]
    after_open = client.calls[open_call_count:verify_call_count]
    assert not any(
        argv[:2] == ["say", "--stdin"]
        and argv[argv.index("--idempotency-key") + 1].endswith(":wake")
        for argv, _body in before_open
    )
    assert any(
        argv[:2] == ["say", "--stdin"]
        and argv[argv.index("--idempotency-key") + 1].endswith(":wake")
        for argv, _body in after_open
    )
