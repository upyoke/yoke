"""Just-in-time grant timing around the exact private wake operation."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
    _driver,
)
from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)


class _VersionGatedReadinessClient(_ScenarioClient):
    def __init__(
        self, cell: AcceptanceCell, *, invalid_operation: bool = False
    ) -> None:
        super().__init__(cell)
        self.invalid_operation = invalid_operation
        self.grant_active = False
        self.readiness_grant_states: list[bool] = []

    def _roster(self, argv: list[str] | None = None) -> dict[str, Any]:
        result = super()._roster(argv)
        for row in result["rows"]:
            if row["session_id"] != self.session_id:
                continue
            row["messageability"]["wake_available"] = surface_operation_supported(
                self.cell.surface,
                self.cell.expected_version,
                "message_stopped",
            )
            if self.invalid_operation:
                row["messageability"]["wake_operation"] = "message_idle"
            self.readiness_grant_states.append(self.grant_active)
        return result

    def _send(self, argv: list[str]) -> dict[str, Any]:
        result = super()._send(argv)
        key = argv[argv.index("--idempotency-key") + 1]
        if key.endswith(":wake") and self.grant_active:
            self.grant_active = False
        return result


class _Qualification:
    def __init__(self, client: _ScenarioClient) -> None:
        self.client = client
        self.events: list[tuple[str, str, int]] = []

    def open(self, _cell: AcceptanceCell, operation: str):
        self.events.append(("open", operation, len(self.client.calls)))
        grant = operation if operation == "message_stopped" else None
        if hasattr(self.client, "grant_active"):
            self.client.grant_active = grant is not None
        return grant

    def verify(self, grant) -> None:
        self.events.append(("verify", str(grant or "none"), len(self.client.calls)))
        if grant is not None and hasattr(self.client, "grant_active"):
            assert self.client.grant_active is False


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


def test_unproven_private_wake_readiness_precedes_scoped_grant() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.241", "create", wake_route="direct")
    assert not surface_operation_supported(
        cell.surface, cell.expected_version, "message_stopped"
    )
    client = _VersionGatedReadinessClient(cell)
    qualification = _Qualification(client)

    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="stage-proof-version-gated-readiness",
        timeout=10,
        poll=1,
        unsupported_observation=2,
        qualification=qualification,
    )

    assert report["status"] == "passed"
    assert client.readiness_grant_states == [False, False]
    assert [event[:2] for event in qualification.events] == [
        ("open", "message_stopped"),
        ("verify", "message_stopped"),
    ]
    open_call_count = qualification.events[0][2]
    assert client.calls[open_call_count - 1][0][:2] == ["sessions", "list"]
    assert client.grant_active is False


def test_candidate_readiness_failure_opens_no_private_wake_grant() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.241", "create", wake_route="direct")
    client = _VersionGatedReadinessClient(cell, invalid_operation=True)
    qualification = _Qualification(client)

    with pytest.raises(AcceptanceContractError) as failure:
        _driver(client)._run_cell(
            "yoke",
            cell,
            run_id="stage-proof-invalid-readiness-operation",
            timeout=10,
            poll=1,
            unsupported_observation=2,
            qualification=qualification,
        )

    assert failure.value.code == "waiting_route_missing"
    assert qualification.events == []
    assert client.grant_active is False
