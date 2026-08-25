"""Just-in-time grant timing around the exact private acceptance operation."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    acceptance_operation,
)
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
    _driver,
)
from runtime.api.tools.test_session_control_live_acceptance_policy_support import (
    CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION,
    require_exact_desktop_active_policy,
)
from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)


# A synthetic exact policy keeps one unproven route available for timing tests.
UNPROVEN_PRIVATE_ROUTE_CELL = AcceptanceCell(
    "claude-desktop",
    CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION,
    "identify",
    session_id="desktop-session",
    wake_route="none",
)
# The send each private route carries: an active-message grant covers the
# initial delivery, a stopped-session grant covers the wake.
_GRANTED_SEND_KEY_SUFFIX = {"message_active": ":initial", "message_stopped": ":wake"}


@pytest.fixture(autouse=True)
def _exact_desktop_active_policy(monkeypatch) -> None:
    require_exact_desktop_active_policy(monkeypatch)


def _granted_send(argv: list[str], suffix: str) -> bool:
    return argv[:2] == ["say", "--stdin"] and argv[
        argv.index("--idempotency-key") + 1
    ].endswith(suffix)


class _VersionGatedReadinessClient(_ScenarioClient):
    def __init__(
        self, cell: AcceptanceCell, *, invalid_operation: bool = False
    ) -> None:
        super().__init__(cell)
        self.invalid_operation = invalid_operation
        self.granted_send_suffix = _GRANTED_SEND_KEY_SUFFIX[
            acceptance_operation(cell.surface)
        ]
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
        if key.endswith(self.granted_send_suffix) and self.grant_active:
            self.grant_active = False
        return result


class _Qualification:
    """Grant only the operation this surface is accepted on."""

    def __init__(self, client: _ScenarioClient) -> None:
        self.client = client
        self.granted_operation = acceptance_operation(client.cell.surface)
        self.events: list[tuple[str, str, int]] = []

    def open(self, _cell: AcceptanceCell, operation: str):
        self.events.append(("open", operation, len(self.client.calls)))
        grant = operation if operation == self.granted_operation else None
        if hasattr(self.client, "grant_active"):
            self.client.grant_active = grant is not None
        return grant

    def verify(self, grant) -> None:
        self.events.append(("verify", str(grant or "none"), len(self.client.calls)))
        if grant is not None and hasattr(self.client, "grant_active"):
            assert self.client.grant_active is False


def test_private_grant_opens_just_before_delivery_and_verifies_after_ack() -> None:
    cell = UNPROVEN_PRIVATE_ROUTE_CELL
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
        ("open", "message_active"),
        ("verify", "message_active"),
        ("open", "message_stopped"),
        ("verify", "none"),
    ]
    open_call_count = qualification.events[0][2]
    verify_call_count = qualification.events[1][2]
    before_open = client.calls[:open_call_count]
    after_open = client.calls[open_call_count:verify_call_count]
    suffix = _GRANTED_SEND_KEY_SUFFIX[qualification.granted_operation]
    assert not any(_granted_send(argv, suffix) for argv, _body in before_open)
    assert any(_granted_send(argv, suffix) for argv, _body in after_open)
    assert any(argv[:2] == ["messages", "get"] for argv, _body in after_open)


def test_unproven_private_route_readiness_reads_precede_scoped_grant() -> None:
    cell = UNPROVEN_PRIVATE_ROUTE_CELL
    assert not surface_operation_supported(
        cell.surface, cell.expected_version, acceptance_operation(cell.surface)
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
    assert client.readiness_grant_states == [False, False, False]
    assert [event[:2] for event in qualification.events] == [
        ("open", "message_active"),
        ("verify", "message_active"),
        ("open", "message_stopped"),
        ("verify", "none"),
    ]
    open_call_count = qualification.events[0][2]
    assert client.calls[open_call_count - 1][0][:2] == ["sessions", "list"]
    assert client.grant_active is False


def test_readiness_failure_opens_no_wake_route_grant() -> None:
    cell = UNPROVEN_PRIVATE_ROUTE_CELL
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
    assert [event[:2] for event in qualification.events] == [
        ("open", "message_active"),
        ("verify", "message_active"),
    ]
    assert client.grant_active is False
