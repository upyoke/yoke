"""One-hop broker route assertions for Fleet live acceptance."""

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


def _broker_cell() -> AcceptanceCell:
    return AcceptanceCell(
        "codex-cli",
        "0.148.0-alpha.15",
        "identify",
        session_id="broker-target-session",
        machine_id="machine-1",
        acceptance_role="broker",
        wake_route="broker",
        broker_session_id="broker-peer-session",
    )


def test_identified_peer_cell_proves_one_hop_broker_identity_and_dedupe() -> None:
    cell = _broker_cell()
    client = _ScenarioClient(cell)

    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="release-broker",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    wake = report["wake_message"]["native_wake"]
    assert report["wake_route"] == "broker"
    assert wake["attempt_kind"] == "wake_broker"
    assert wake["broker_session_id"] == "broker-peer-session"
    assert wake["attempt_deduplicated"] is True
    assert wake["native_traffic_body_free"] is True
    assert "MUST-NOT-ENTER-REPORT" not in json.dumps(report)
    roster_calls = [
        argv for argv, _body in client.calls if argv[:2] == ["sessions", "list"]
    ]
    assert roster_calls
    assert all("--session" in argv and "--limit" not in argv for argv in roster_calls)
    assert {argv[argv.index("--session") + 1] for argv in roster_calls} == {
        "broker-target-session",
        "broker-peer-session",
    }


def test_broker_cell_fails_closed_on_wrong_peer_duplicate_or_missing_digest() -> None:
    cell = _broker_cell()
    scenarios = (
        (
            _ScenarioClient(cell, broker_identity_mismatch=True),
            "wake_broker_identity_mismatch",
        ),
        (
            _ScenarioClient(cell, duplicate_wake_attempt=True),
            "wake_attempt_count_invalid",
        ),
        (
            _ScenarioClient(cell, missing_instruction_digest=True),
            "native_instruction_evidence_missing",
        ),
        (
            _ScenarioClient(cell, attempts_truncated=True),
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
