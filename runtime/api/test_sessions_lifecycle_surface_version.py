"""Reactivation keeps executor_version paired with executor_surface.

Companion to ``test_sessions_lifecycle_executor.py``; split out so both
files stay under the 350-line authored cap.
"""

from __future__ import annotations

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.sessions import end_session
from yoke_core.domain.sessions_lifecycle_identity import (
    resolve_reactivation_executor_version,
)
from runtime.api.test_sessions import _register

pytest_plugins = ("runtime.api.test_sessions",)


_APP_VERSION = "1.34493.1"
_CLI_VERSION = "2.1.245"
_KEPT_DIGEST = "sha256:kept-wake-instruction"


def _p(connection):
    return "%s" if db_backend.connection_is_postgres(connection) else "?"


def _ensure_attempts_table(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS session_message_attempts (
            attempt_id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            target_session_id TEXT NOT NULL,
            broker_session_id TEXT,
            attempt_kind TEXT NOT NULL,
            adapter_revision TEXT,
            lease_id TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            result_code TEXT,
            evidence TEXT
        )
        """
    )
    connection.commit()


def _insert_open_wake_attempt(connection, session_id: str) -> None:
    _ensure_attempts_table(connection)
    marker = _p(connection)
    connection.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id, message_id, target_session_id, attempt_kind, "
        f"started_at, evidence) VALUES ({marker},{marker},{marker},"
        f"{marker},{marker},{marker})",
        (
            f"attempt-{session_id}",
            "message-1",
            session_id,
            "wake_relay",
            "2026-08-25T15:00:00Z",
            json_helper.dumps_compact({"native_instruction_sha256": _KEPT_DIGEST}),
        ),
    )
    connection.commit()


def _attempt_evidence(connection, session_id: str) -> dict:
    marker = _p(connection)
    row = connection.execute(
        "SELECT evidence FROM session_message_attempts "
        f"WHERE target_session_id = {marker}",
        (session_id,),
    ).fetchone()
    assert row is not None
    payload = json_helper.loads_text(str(row["evidence"]))
    assert isinstance(payload, dict)
    return payload


def test_resolve_keeps_version_when_surfaces_differ() -> None:
    existing = {
        "executor_surface": "claude-desktop",
        "executor_version": _APP_VERSION,
    }
    assert (
        resolve_reactivation_executor_version(
            existing,
            incoming_surface="claude-cli",
            incoming_version=_CLI_VERSION,
        )
        == _APP_VERSION
    )


def test_resolve_refreshes_version_when_surface_matches() -> None:
    existing = {
        "executor_surface": "claude-desktop",
        "executor_version": _APP_VERSION,
    }
    assert (
        resolve_reactivation_executor_version(
            existing,
            incoming_surface="claude-desktop",
            incoming_version="1.40000.0",
        )
        == "1.40000.0"
    )


def test_cli_wake_keeps_desktop_app_version_and_records_driver(conn) -> None:
    session_id = "desktop-ended"
    result = _register(
        conn,
        session_id=session_id,
        executor="claude-desktop",
        executor_version=_APP_VERSION,
    )
    assert result["executor_surface"] == "claude-desktop"
    assert result["executor_version"] == _APP_VERSION
    end_session(conn, session_id)
    _insert_open_wake_attempt(conn, session_id)

    woken = _register(
        conn,
        session_id=session_id,
        executor="claude-cli",
        executor_version=_CLI_VERSION,
    )
    assert woken["executor_surface"] == "claude-desktop"
    assert woken["executor_version"] == _APP_VERSION
    evidence = _attempt_evidence(conn, session_id)
    assert evidence["driver_surface"] == "claude-cli"
    assert evidence["driver_version"] == _CLI_VERSION
    assert evidence["native_instruction_sha256"] == _KEPT_DIGEST


def test_fresh_cli_session_stamps_cli_version(conn) -> None:
    result = _register(
        conn,
        session_id="cli-fresh",
        executor="claude-cli",
        executor_version=_CLI_VERSION,
    )
    assert result["executor_surface"] == "claude-cli"
    assert result["executor_version"] == _CLI_VERSION


def test_same_surface_reregistration_refreshes_version(conn) -> None:
    session_id = "desktop-refresh"
    _register(
        conn,
        session_id=session_id,
        executor="claude-desktop",
        executor_version=_APP_VERSION,
    )
    end_session(conn, session_id)
    refreshed = _register(
        conn,
        session_id=session_id,
        executor="claude-desktop",
        executor_version="1.40000.0",
    )
    assert refreshed["executor_surface"] == "claude-desktop"
    assert refreshed["executor_version"] == "1.40000.0"
