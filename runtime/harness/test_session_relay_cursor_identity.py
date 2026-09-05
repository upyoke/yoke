"""Cursor vendor-created identity resolution from launch registration."""

from __future__ import annotations

from yoke_harness.session_relay_cursor_identity import (
    CURSOR_REGISTRATION_LOOKUP_ATTEMPTS,
    resolve_registered_session,
)


SESSION_ID = "22222222-2222-4222-8222-222222222222"


def test_registration_lookup_retries_until_the_server_has_a_candidate() -> None:
    calls = []
    results = iter(
        (
            {"status": "registration_pending"},
            {"status": "registered_but_unbound", "session_id": SESSION_ID},
        )
    )

    resolution = resolve_registered_session(
        lambda workspace: calls.append(workspace) or next(results),
        "/project",
    )

    assert resolution.session_id == SESSION_ID
    assert resolution.result_code == "registered_but_unbound"
    assert resolution.attempts == 2
    assert calls == ["/project", "/project"]


def test_already_bound_registration_is_a_valid_identity() -> None:
    resolution = resolve_registered_session(
        lambda _workspace: {
            "status": "registration_bound",
            "session_id": SESSION_ID,
        },
        "/project",
    )

    assert resolution.session_id == SESSION_ID
    assert resolution.result_code == "registration_bound"


def test_missing_candidate_stays_pending_after_the_bounded_reads() -> None:
    calls = []

    resolution = resolve_registered_session(
        lambda workspace: calls.append(workspace) or {"status": "registration_pending"},
        "/project",
    )

    assert resolution.session_id is None
    assert resolution.result_code == "registration_pending"
    assert resolution.attempts == CURSOR_REGISTRATION_LOOKUP_ATTEMPTS
    assert calls == ["/project"] * CURSOR_REGISTRATION_LOOKUP_ATTEMPTS


def test_invalid_registered_candidate_fails_closed() -> None:
    resolution = resolve_registered_session(
        lambda _workspace: {
            "status": "registered_but_unbound",
            "session_id": "not-a-session-id",
        },
        "/project",
    )

    assert resolution.session_id is None
    assert resolution.result_code == "registered_session_invalid"


def test_unavailable_registration_surface_is_named_without_a_read() -> None:
    resolution = resolve_registered_session(None, "/project")

    assert resolution.session_id is None
    assert resolution.result_code == "registration_lookup_unavailable"
    assert resolution.attempts == 0
