from runtime.api.tools.session_control_live_acceptance_driver_test_support import (
    RELEASE_SHA as RELEASE_SHA,
    SERVER_BUILD as SERVER_BUILD,
    _ScenarioClient as _ScenarioClient,
    _driver as _driver,
)

import json

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceMatrix,
)


def test_create_cell_requires_binding_ack_wait_wake_and_dedupe() -> None:
    cell = AcceptanceCell("codex-cli", "0.148.0-alpha.15", "create")
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
    assert report["wake_message"]["native_wake"]["attempt_kind"] == "wake_relay"
    assert report["wake_message"]["native_wake"]["native_traffic_body_free"] is True
    assert report["initial_deduplicated"] is True
    assert report["wake_deduplicated"] is True
    rendered = json.dumps(report)
    assert "MUST-NOT-ENTER-REPORT" not in rendered
    for argv, body in client.calls:
        if body:
            assert body not in argv
            assert "--stdin" in argv


def test_known_unwakeable_surface_records_observable_skip() -> None:
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
    assert report["wake_outcome"] == "expected_unsupported"
    assert report["wake_message"]["state"] == "pending"
    assert report["wake_message"]["wake_attempt_count"] == 1
    assert report["wake_message"]["native_wake"]["route"] == "none"
    assert report["wake_message"]["native_wake"]["result_code"] == "skipped_surface"


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
