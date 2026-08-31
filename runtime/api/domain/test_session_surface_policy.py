"""Surface disable marks: storage, launch exclusion, and refusal text."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.session_message_wake import _native_wake_route_available
from yoke_core.domain.session_message_wake_skip import _wake_skip_result
from yoke_core.domain.session_surface_policy import (
    SURFACE_DISABLED_REJECTION,
    WAKE_SKIP_SURFACE_DISABLED,
    clear_mark,
    enable_command,
    list_marks,
    live_mark,
    set_mark,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
)


def _disable(conn, *, machine_id="machine-1", surface="codex-cli", reason="quota"):
    return set_mark(
        conn,
        machine_id=machine_id,
        surface=surface,
        reason=reason,
        actor_id=1,
        session_id="caller",
        now=NOW,
    )


def test_one_live_mark_per_machine_surface_and_clear_records_who() -> None:
    conn = launch_connection()
    first = _disable(conn, reason="quota_exhausted")
    second = _disable(conn, reason="launch_path_broken")
    assert first["mark_id"] == second["mark_id"]
    assert live_mark(conn, "machine-1", "codex-cli")["reason"] == "launch_path_broken"
    assert len(list_marks(conn, machine_id="machine-1")) == 1

    cleared = clear_mark(conn, machine_id="machine-1", surface="codex-cli", actor_id=2)
    assert cleared["cleared_by_actor_id"] == 2
    assert live_mark(conn, "machine-1", "codex-cli") is None
    assert list_marks(conn, include_cleared=True)[0]["cleared_at"]


def test_eligibility_excludes_a_disabled_machine_surface() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="fresh", last_seen_at="2026-08-22T11:59:00Z")
    _disable(conn)

    snapshot = derive_launch_eligibility(
        conn,
        project_id=10,
        surface="codex-cli",
        machine_id=None,
        now=NOW,
    )

    assert snapshot.relays == ()
    assert SURFACE_DISABLED_REJECTION in snapshot.rejection_codes


def test_create_refusal_names_mark_reason_and_enable_command() -> None:
    conn = launch_connection()
    add_relay(conn)
    _disable(conn, reason="quota_exhausted")

    with pytest.raises(SessionLaunchError) as raised:
        create_launch(
            conn,
            auth=authorization(),
            request=LaunchRequest(
                project_id=10,
                executor_surface="codex-cli",
                instructions="Start one bounded task.",
                idempotency_key="surface-disabled",
            ),
            now=NOW,
        )

    text = str(raised.value)
    assert raised.value.code == "no_eligible_relay"
    assert "quota_exhausted" in text
    assert enable_command("machine-1", "codex-cli") in text


def test_native_wake_skips_a_disabled_surface() -> None:
    conn = launch_connection()
    _disable(conn, surface="cursor-cli")
    row = {
        "machine_id": "machine-1",
        "executor_surface": "cursor-cli",
        "terminated_at": None,
    }
    assert (
        _native_wake_route_available(
            conn,
            row,
            liveness="ended",
            operation="create",
            relay_versions={"cursor-cli": "2026.08.11-e8db854"},
        )
        is False
    )
    code, _driver, reason = _wake_skip_result(
        row, "create", {"cursor-cli": "2026.08.11-e8db854"}, conn=conn
    )
    assert code == WAKE_SKIP_SURFACE_DISABLED
    assert reason == "surface_policy_disabled"
