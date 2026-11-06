"""Registration lookups require exact identity; directory/time is never ownership."""

import pytest

from yoke_core.domain.session_launch_execution import (
    reconcile_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration_candidate import (
    reserve_launch_registration_candidate,
)
from yoke_core.domain.session_launch_store import get_launch
from runtime.api.domain.session_launch_test_support import (
    add_relay,
    authorization,
    relay_connection,
)
from runtime.api.domain.session_launch_attested_binding_test_support import (
    bind,
    registered_launch,
)


def connection():
    conn = relay_connection()
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN episode_started_at TEXT")
    add_relay(conn)
    return conn


def reserve(conn, launch, claim):
    return reserve_launch_registration_candidate(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        now="2026-08-22T12:00:03Z",
    )


def native_progress(conn, launch, *, session=None):
    conn.execute(
        "UPDATE session_launch_attempts SET evidence=? WHERE launch_id=?",
        (
            '{"native_launch_workspace":"/project","native_launch_bound_seconds":120}',
            launch.launch_id,
        ),
    )
    if session:
        conn.execute(
            "UPDATE session_launches SET native_session_id=? WHERE launch_id=?",
            (session, launch.launch_id),
        )
    conn.commit()


@pytest.mark.parametrize("session_count", (1, 2))
def test_same_directory_sessions_are_not_launch_identity(session_count):
    conn = connection()
    launch, claim, _session = registered_launch(conn, "codex-cli", "unattested")
    if session_count == 2:
        registered_launch(conn, "codex-cli", "another")
    native_progress(conn, launch)
    assert reserve(conn, launch, claim) == {"status": "registration_pending"}
    assert get_launch(conn, launch.launch_id).native_session_id is None


def test_relay_proven_exact_native_can_be_reserved_without_guessing():
    conn = connection()
    launch, claim, session = registered_launch(conn, "codex-cli", "exact-native")
    registered_launch(conn, "codex-cli", "unrelated")
    native_progress(conn, launch, session=session)
    result = reserve(conn, launch, claim)
    assert result["status"] == "registered_but_unbound"
    assert result["session_id"] == session


@pytest.mark.parametrize(
    "column,value",
    (
        ("workspace", "/other"),
        ("executor_surface", "cursor-cli"),
        ("machine_id", "other-machine"),
    ),
)
def test_exact_native_still_requires_its_spawn_context(column, value):
    conn = connection()
    launch, claim, session = registered_launch(conn, "codex-cli", "wrong-context")
    native_progress(conn, launch, session=session)
    conn.execute(
        f"UPDATE harness_sessions SET {column}=? WHERE session_id=?", (value, session)
    )
    conn.commit()
    assert reserve(conn, launch, claim) == {"status": "registration_pending"}


def test_authenticated_hook_binding_does_not_depend_on_window_metadata():
    conn = connection()
    launch, claim, session = registered_launch(conn, "codex-cli", "hook-first")
    bind(conn, launch, claim, session)
    assert reserve(conn, launch, claim) == {
        "status": "registration_bound",
        "session_id": session,
    }


def test_reconcile_does_not_adopt_an_unattested_directory_match():
    conn = connection()
    launch, claim, _session = registered_launch(
        conn, "codex-cli", "no-inferred-adoption"
    )
    native_progress(conn, launch)
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="outcome_unknown",
        evidence={"result_code": "identity_listing_failed"},
        now="2026-08-22T12:00:05Z",
    )
    reconciled = reconcile_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        observed_native_id=None,
        now="2026-08-22T12:30:00Z",
    )
    assert reconciled.state == "failed"
    assert reconciled.result_code == "reconciled_not_created"
    assert reconciled.registered_session_id is None
