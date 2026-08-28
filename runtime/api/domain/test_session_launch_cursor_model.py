"""Launch-bound cursor sessions store requested_model in the one model field."""

from __future__ import annotations

from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import prepare_launch_registration
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)


def _cursor_relay(conn) -> None:
    add_relay(conn, surface="cursor-cli", version="2026.08.25-3e8eec8")


def _awaiting(conn, *, key: str, surface: str, model: str):
    launch = assigned_launch(conn, key=key, surface=surface, model=model)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    awaiting = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=f"session-{key}",
        now="2026-08-22T12:00:30Z",
    )
    return awaiting, claim


def _candidate(conn, *, session_id: str, surface: str, model: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, "
        "machine_id, model) VALUES (?, 10, ?, '2026.08.25-3e8eec8', "
        "'machine-1', ?)",
        (session_id, surface, model),
    )
    conn.commit()


def _stored_model(conn, session_id: str) -> str:
    row = conn.execute(
        "SELECT model FROM harness_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return str(row["model"] if row is not None else "")


def test_cursor_launch_bind_stores_requested_model_as_session_model() -> None:
    conn = launch_connection()
    _cursor_relay(conn)
    launch, claim = _awaiting(
        conn,
        key="cursor-tier",
        surface="cursor-cli",
        model="cursor-grok-4.6-xhigh",
    )
    _candidate(
        conn,
        session_id="session-cursor-tier",
        surface="cursor-cli",
        model="grok-4.6",
    )

    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-cursor-tier",
        now="2026-08-22T12:00:31Z",
    )

    assert _stored_model(conn, "session-cursor-tier") == "cursor-grok-4.6-xhigh"


def test_non_cursor_launch_keeps_payload_self_report() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _awaiting(
        conn,
        key="codex-keep",
        surface="codex-cli",
        model="gpt-5.6-sol",
    )
    _candidate(
        conn,
        session_id="session-codex-keep",
        surface="codex-cli",
        model="gpt-5.6-sol",
    )

    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-codex-keep",
        now="2026-08-22T12:00:31Z",
    )

    assert _stored_model(conn, "session-codex-keep") == "gpt-5.6-sol"


def test_cursor_session_without_requested_model_keeps_bare_self_report() -> None:
    conn = launch_connection()
    _cursor_relay(conn)
    launch, claim = _awaiting(
        conn,
        key="cursor-bare",
        surface="cursor-cli",
        model=None,
    )
    _candidate(
        conn,
        session_id="session-cursor-bare",
        surface="cursor-cli",
        model="grok-4.6",
    )

    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-cursor-bare",
        now="2026-08-22T12:00:31Z",
    )

    assert _stored_model(conn, "session-cursor-bare") == "grok-4.6"


def test_heal_restores_requested_model_on_already_bound_cursor_session() -> None:
    from yoke_core.domain.session_launch_cursor_model import (
        heal_cursor_session_model_from_launch,
    )

    conn = launch_connection()
    _cursor_relay(conn)
    launch, claim = _awaiting(
        conn,
        key="cursor-heal",
        surface="cursor-cli",
        model="cursor-grok-4.6-xhigh",
    )
    _candidate(
        conn,
        session_id="session-cursor-heal",
        surface="cursor-cli",
        model="grok-4.6",
    )
    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id="session-cursor-heal",
        now="2026-08-22T12:00:31Z",
    )
    conn.execute(
        "UPDATE harness_sessions SET model = ? WHERE session_id = ?",
        ("grok-4.6", "session-cursor-heal"),
    )
    conn.commit()

    healed = heal_cursor_session_model_from_launch(
        conn, "session-cursor-heal", "cursor-cli"
    )

    assert healed == "cursor-grok-4.6-xhigh"
    assert _stored_model(conn, "session-cursor-heal") == "cursor-grok-4.6-xhigh"
