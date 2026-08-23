"""Focused tests for launch preview, persistence, cancellation, and idempotency."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_requests import (
    cancel_launch,
    create_launch,
    preview_launch,
)
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
)


def test_eligibility_uses_live_versions_projects_and_freshest_relay_per_machine() -> (
    None
):
    conn = launch_connection()
    add_relay(conn, relay_id="old", last_seen_at="2026-08-22T11:58:00Z")
    add_relay(conn, relay_id="fresh", last_seen_at="2026-08-22T11:59:00Z")
    add_relay(
        conn,
        relay_id="stale-version",
        machine_id="machine-2",
        version="0.147.0",
    )
    add_relay(
        conn,
        relay_id="wrong-project",
        machine_id="machine-3",
        projects=[99],
    )

    snapshot = derive_launch_eligibility(
        conn,
        project_id=10,
        surface="codex-cli",
        machine_id=None,
        now=NOW,
    )

    assert [relay.relay_id for relay in snapshot.relays] == ["fresh"]
    assert snapshot.rejection_codes == ("project_checkout_missing", "version_mismatch")


def test_eligibility_accepts_cursor_build_version() -> None:
    conn = launch_connection()
    add_relay(
        conn,
        surface="cursor-cli",
        version="2026.08.11-e8db854",
    )

    snapshot = derive_launch_eligibility(
        conn,
        project_id=10,
        surface="cursor-cli",
        machine_id=None,
        now=NOW,
    )

    assert [relay.relay_id for relay in snapshot.relays] == ["relay-1"]
    assert snapshot.rejection_codes == ()


def test_preview_requires_machine_when_multiple_eligible_machines_exist() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="r1", machine_id="m1")
    add_relay(conn, relay_id="r2", machine_id="m2")

    ambiguous = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-cli",
        now=NOW,
    )
    selected = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-cli",
        machine_id="m2",
        now=NOW,
    )

    assert ambiguous.outcome == "machine_required"
    assert selected.selected_relay and selected.selected_relay.relay_id == "r2"


def test_preview_refuses_unsupported_create_surface() -> None:
    conn = launch_connection()
    result = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="claude-desktop",
        now=NOW,
    )
    assert result.outcome == "unsupported_surface"


def test_create_stores_instructions_once_and_deduplicates_exact_request() -> None:
    conn = launch_connection()
    add_relay(conn)
    request = LaunchRequest(
        project_id=10,
        executor_surface="codex-cli",
        instructions="Do the bounded task.",
        idempotency_key="same-request",
        model="gpt-5",
    )

    first = create_launch(conn, auth=authorization(), request=request, now=NOW)
    second = create_launch(conn, auth=authorization(), request=request, now=NOW)

    assert first.launch.state == "assigned"
    assert second.launch.launch_id == first.launch.launch_id
    assert second.deduplicated is True
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 1
    message = conn.execute(
        "SELECT body FROM session_messages WHERE message_id = ?",
        (first.launch.message_id,),
    ).fetchone()
    assert message[0] == request.instructions


def test_idempotency_key_refuses_changed_body() -> None:
    conn = launch_connection()
    add_relay(conn)
    base = LaunchRequest(
        project_id=10,
        executor_surface="codex-cli",
        instructions="First body",
        idempotency_key="fixed-key",
    )
    create_launch(conn, auth=authorization(), request=base, now=NOW)

    with pytest.raises(SessionLaunchError, match="different launch request") as raised:
        create_launch(
            conn,
            auth=authorization(),
            request=LaunchRequest(**{**base.__dict__, "instructions": "Changed body"}),
            now=NOW,
        )
    assert raised.value.code == "idempotency_conflict"
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 1


def test_create_requires_operator_authorization() -> None:
    conn = launch_connection()
    add_relay(conn)
    with pytest.raises(SessionLaunchError) as raised:
        create_launch(
            conn,
            auth=authorization(operator=False),
            request=LaunchRequest(
                project_id=10,
                executor_surface="codex-cli",
                instructions="No authority",
                idempotency_key="denied",
            ),
            now=NOW,
        )
    assert raised.value.code == "permission_denied"


def test_only_requester_or_project_admin_can_cancel() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = create_launch(
        conn,
        auth=authorization(),
        request=LaunchRequest(
            project_id=10,
            executor_surface="codex-cli",
            instructions="Cancel me",
            idempotency_key="cancel-me",
        ),
        now=NOW,
    ).launch

    with pytest.raises(SessionLaunchError) as raised:
        cancel_launch(
            conn,
            launch_id=launch.launch_id,
            auth=authorization(actor_id=2),
            now=NOW,
        )
    assert raised.value.code == "permission_denied"
    cancelled = cancel_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(actor_id=3, admin=True),
        now=NOW,
    )
    assert cancelled.state == "cancelled"
