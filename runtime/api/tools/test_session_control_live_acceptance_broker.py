"""Route-selection assertions for the broker-capable acceptance cell."""

from __future__ import annotations

import json

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    AcceptanceMatrix,
)
from runtime.api.tools.session_control_live_acceptance_wake_route import (
    MACHINE_SELECTED_ROUTE,
)
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    RELEASE_SHA,
    SERVER_BUILD,
    _ScenarioClient,
    _driver,
)


def _broker_cell() -> AcceptanceCell:
    return AcceptanceCell(
        "codex-cli",
        "0.148.0-alpha.15",
        "identify",
        session_id="broker-target-session",
        machine_id="machine-1",
        acceptance_role="broker",
        wake_route=MACHINE_SELECTED_ROUTE,
        broker_session_id="broker-peer-session",
    )


def _run(client: _ScenarioClient, run_id: str) -> dict[str, object]:
    return _driver(client)._run_cell(
        "yoke",
        client.cell,
        run_id=run_id,
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )


def test_fresh_machine_relay_selects_the_direct_route_and_delivers() -> None:
    client = _ScenarioClient(_broker_cell(), machine_relay_fresh=True)

    report = _run(client, "release-broker-relay-fresh")

    selection = report["route_selection"]
    wake = report["wake_message"]["native_wake"]
    assert report["status"] == "passed"
    assert report["wake_route"] == MACHINE_SELECTED_ROUTE
    assert selection["selected_route"] == "direct"
    assert selection["machine_relay_fresh"] is True
    assert selection["exercised_branch"] == "machine_relay_fresh"
    assert selection["unexercised_branch"] == "machine_relay_absent"
    assert selection["unexercised_verdict"] == "designed_not_exercisable"
    assert selection["unexercised_condition"] == "machine_relay_fresh"
    assert wake["attempt_kind"] == "wake_relay"
    assert wake["broker_session_id"] is None
    assert report["wake_message"]["state"] == "acknowledged"
    assert wake["native_traffic_body_free"] is True
    assert "MUST-NOT-ENTER-REPORT" not in json.dumps(report)


def test_absent_machine_relay_selects_the_one_hop_broker_and_delivers() -> None:
    client = _ScenarioClient(_broker_cell(), machine_relay_fresh=False)

    report = _run(client, "release-broker-relay-absent")

    selection = report["route_selection"]
    wake = report["wake_message"]["native_wake"]
    assert report["status"] == "passed"
    assert selection["selected_route"] == "broker"
    assert selection["machine_relay_fresh"] is False
    assert selection["exercised_branch"] == "machine_relay_absent"
    assert selection["unexercised_branch"] == "machine_relay_fresh"
    assert selection["unexercised_verdict"] == "designed_not_exercisable"
    assert wake["attempt_kind"] == "wake_broker"
    assert wake["broker_session_id"] == "broker-peer-session"
    assert wake["attempt_deduplicated"] is True
    roster_calls = [
        argv for argv, _body in client.calls if argv[:2] == ["sessions", "list"]
    ]
    assert roster_calls
    assert all("--session" in argv and "--limit" not in argv for argv in roster_calls)
    assert {argv[argv.index("--session") + 1] for argv in roster_calls} == {
        "broker-target-session",
        "broker-peer-session",
    }


@pytest.mark.parametrize("machine_relay_fresh", (True, False))
def test_a_route_the_machine_did_not_select_fails_closed(
    machine_relay_fresh: bool,
) -> None:
    client = _ScenarioClient(
        _broker_cell(),
        machine_relay_fresh=machine_relay_fresh,
        wake_route_defect=True,
    )

    with pytest.raises(AcceptanceContractError) as failure:
        _run(client, "release-broker-route-defect")

    assert failure.value.code == "wake_route_mismatch"


def test_unreadable_machine_relay_presence_fails_closed() -> None:
    client = _ScenarioClient(_broker_cell())
    roster = client._roster

    def _without_relay_presence(argv: list[str] | None = None) -> dict[str, object]:
        result = roster(argv)
        for row in result["rows"]:
            row["messageability"].pop("relay_connected", None)
        return result

    client._roster = _without_relay_presence
    with pytest.raises(AcceptanceContractError) as failure:
        _run(client, "release-broker-relay-unreadable")

    assert failure.value.code == "machine_relay_presence_unreadable"


def test_broker_branch_fails_closed_on_wrong_peer_duplicate_or_missing_digest() -> None:
    cell = _broker_cell()
    scenarios = (
        (
            _ScenarioClient(
                cell, machine_relay_fresh=False, broker_identity_mismatch=True
            ),
            "wake_broker_identity_mismatch",
        ),
        (
            _ScenarioClient(
                cell, machine_relay_fresh=False, duplicate_wake_attempt=True
            ),
            "wake_attempt_count_invalid",
        ),
        (
            _ScenarioClient(
                cell, machine_relay_fresh=False, missing_instruction_digest=True
            ),
            "native_instruction_evidence_missing",
        ),
        (
            _ScenarioClient(cell, machine_relay_fresh=False, attempts_truncated=True),
            "attempt_evidence_incomplete",
        ),
    )

    for index, (client, failure_code) in enumerate(scenarios):
        report = _driver(client).run(
            AcceptanceMatrix("yoke", (cell,)),
            run_id=f"release-broker-failure-{index}",
            release_sha=RELEASE_SHA,
            server_build=SERVER_BUILD,
            engine_version="0.1.1+launch.999",
            caller_session_id="main-session",
            timeout_seconds=10,
            poll_seconds=1,
            unsupported_observation_seconds=2,
        )
        assert report["cells"][0]["failure_code"] == failure_code


def test_broker_cell_requires_same_machine_peer() -> None:
    cell = _broker_cell()
    client = _ScenarioClient(cell, broker_machine_mismatch=True)
    report = _driver(client).run(
        AcceptanceMatrix("yoke", (cell,)),
        run_id="release-broker-route",
        release_sha=RELEASE_SHA,
        server_build=SERVER_BUILD,
        engine_version="0.1.1+launch.999",
        caller_session_id="main-session",
        timeout_seconds=10,
        poll_seconds=1,
        unsupported_observation_seconds=2,
    )
    assert report["cells"][0]["failure_code"] == "broker_machine_mismatch"
