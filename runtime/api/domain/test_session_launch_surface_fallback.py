"""Explicit launch-surface fallback selection and persisted identity tests."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_launch_execution import report_launch_attempt
from yoke_core.domain.session_launch_registration import prepare_launch_registration
from yoke_core.domain.session_launch_requests import (
    create_launch,
    preview_launch,
    retry_launch,
)
from yoke_core.domain.session_launch_store import update_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.session_relay_jobs import claim_launch_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
)


def _request(*, key: str = "fallback") -> LaunchRequest:
    return LaunchRequest(
        project_id=10,
        executor_surface="codex-vscode",
        instructions="Use the selected native surface and register.",
        idempotency_key=key,
        allow_surface_fallback=True,
    )


@pytest.mark.parametrize(
    ("request_gate", "organization_gate", "expected"),
    (
        (False, False, "unsupported_surface"),
        (False, True, "unsupported_surface"),
        (True, False, "surface_fallback_disabled"),
        (True, True, "assigned_fallback"),
    ),
)
def test_fallback_requires_request_and_organization_gates(
    request_gate: bool,
    organization_gate: bool,
    expected: str,
) -> None:
    conn = launch_connection()
    add_relay(conn, surface="codex-cli")

    preview = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-vscode",
        allow_surface_fallback=request_gate,
        surface_fallback_enabled=organization_gate,
        now=NOW,
    )

    assert preview.outcome == expected
    assert preview.launchable is (request_gate and organization_gate)


def test_exact_surface_wins_even_when_fallback_is_enabled() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="exact", machine_id="m1", surface="codex-cli")
    add_relay(
        conn,
        relay_id="alternative",
        machine_id="m2",
        surface="codex-desktop",
        version="26.814.41407",
    )

    preview = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-cli",
        allow_surface_fallback=True,
        surface_fallback_enabled=True,
        now=NOW,
    )

    assert preview.selected_surface == "codex-cli"
    assert preview.fallback_used is False
    assert preview.selected_relay and preview.selected_relay.relay_id == "exact"


def test_fallback_is_same_family_version_proven_and_deterministic() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="cli", surface="codex-cli", machine_id="m1")
    add_relay(
        conn,
        relay_id="desktop",
        surface="codex-desktop",
        version="26.814.41407",
        machine_id="m1",
    )
    add_relay(
        conn,
        relay_id="cross-family",
        surface="cursor-cli",
        version="2026.08.11-e8db854",
        machine_id="m2",
    )

    preview = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-vscode",
        allow_surface_fallback=True,
        surface_fallback_enabled=True,
        now=NOW,
    )
    refused = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="claude-desktop",
        allow_surface_fallback=True,
        surface_fallback_enabled=True,
        now=NOW,
    )

    assert preview.selected_surface == "codex-cli"
    assert preview.fallback_used is True
    assert [relay.relay_id for relay in preview.eligible_relays] == ["cli"]
    assert refused.outcome == "unsupported_surface"
    assert refused.launchable is False


def test_selected_surface_drives_native_job_and_registration() -> None:
    conn = launch_connection()
    add_relay(conn, surface="codex-cli")
    outcome = create_launch(
        conn,
        auth=authorization(),
        request=_request(),
        surface_fallback_enabled=True,
        now=NOW,
    )
    launch = outcome.launch
    heartbeat = RelayHeartbeat(
        relay_id="relay-1",
        actor_id=1,
        machine_id="machine-1",
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )

    job = claim_launch_job(conn, heartbeat, now=NOW)

    assert launch.requested_surface == "codex-vscode"
    assert launch.selected_surface == "codex-cli"
    assert outcome.preview.fallback_used is True
    assert job and job.surface == "codex-cli"
    reported = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=job.lease_id,
        result_code="native_created",
        native_session_id="native-fallback",
        now="2026-08-22T12:00:20Z",
    )
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor_surface,executor_version,machine_id,model) "
        "VALUES ('native-fallback',10,'codex-cli','0.148.0a15','machine-1',NULL)"
    )
    conn.commit()

    injection = prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=str(job.launch_attestation),
        session_id="native-fallback",
        now="2026-08-22T12:00:21Z",
    )

    assert reported.selected_surface == "codex-cli"
    assert injection.session_id == "native-fallback"


def test_retry_reselects_without_changing_the_original_request() -> None:
    conn = launch_connection()
    add_relay(conn, surface="codex-cli")
    launch = create_launch(
        conn,
        auth=authorization(),
        request=_request(key="retry"),
        surface_fallback_enabled=True,
        now=NOW,
    ).launch
    update_launch(
        conn,
        launch.launch_id,
        state="failed",
        completed_at="2026-08-22T12:00:20Z",
    )
    conn.execute("UPDATE session_relays SET state='revoked'")
    add_relay(
        conn,
        relay_id="desktop",
        surface="codex-desktop",
        version="26.814.41407",
    )

    with pytest.raises(SessionLaunchError) as gated:
        retry_launch(
            conn,
            launch_id=launch.launch_id,
            auth=authorization(),
            surface_fallback_enabled=False,
            now="2026-08-22T12:00:21Z",
        )
    assert gated.value.code == "surface_fallback_disabled"

    retried = retry_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        surface_fallback_enabled=True,
        now="2026-08-22T12:00:22Z",
    )

    assert retried.requested_surface == "codex-vscode"
    assert retried.selected_surface == "codex-desktop"
