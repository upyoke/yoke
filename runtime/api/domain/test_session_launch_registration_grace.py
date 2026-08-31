"""Launch binding survives idle cleanup long enough to enter its mandate."""

from __future__ import annotations

from yoke_contracts.session_control.launch_bootstrap import (
    AUTOMATIC_LAUNCH_REGISTRATION_TEACHING,
    native_launch_bootstrap,
)
from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import prepare_launch_registration
from yoke_core.domain.session_launch_registration_grace import (
    hold_launch_registration_grace,
)
from yoke_core.domain.session_keepalive import session_keepalive_holds
from yoke_core.domain.session_message_types import parse_timestamp, timestamp, utc_now
from yoke_core.domain.sessions import end_session_if_empty
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)
from runtime.api.test_sessions import _register


pytest_plugins = ("runtime.api.test_sessions",)


WORKER = "launch-grace-worker"


def _reported_launch(conn):
    launch = assigned_launch(conn, key="registration-grace")
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=WORKER,
        now="2026-08-22T12:00:30Z",
    )
    return launch, claim


def _register_worker(conn) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, "
        "machine_id, model) VALUES (?, 10, 'codex-cli', '0.148.0a15', "
        "'machine-1', 'gpt-5')",
        (WORKER,),
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS work_claims ("
        "id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, "
        "target_kind TEXT NOT NULL DEFAULT 'item', released_at TEXT)"
    )
    conn.commit()


def test_bootstrap_says_opening_hook_registration_is_automatic() -> None:
    bootstrap = native_launch_bootstrap("launch-example")

    assert AUTOMATIC_LAUNCH_REGISTRATION_TEACHING in bootstrap
    assert "register, pull your message" not in bootstrap


def test_launch_binding_takes_a_live_registration_grace() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch, claim = _reported_launch(conn)
    _register_worker(conn)
    current = parse_timestamp("2026-08-22T12:00:32Z")
    assert current is not None

    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=WORKER,
        now="2026-08-22T12:00:31Z",
    )
    hold = session_keepalive_holds(conn, (WORKER,), now=current)[WORKER]

    held_until = parse_timestamp(hold["keepalive_until"])
    assert held_until is not None
    assert held_until > current


def test_registration_grace_blocks_empty_end_until_the_worker_can_claim(conn) -> None:
    _register(conn, session_id=WORKER)
    hold_launch_registration_grace(conn, WORKER, now=timestamp(utc_now()))
    conn.commit()

    result = end_session_if_empty(conn, WORKER)

    assert result["status"] == "keepalive_held"
    assert result["ended"] is False
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id = %s", (WORKER,)
    ).fetchone()
    assert row["ended_at"] is None
