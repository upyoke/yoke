# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.session_message_machine_wake_route_test_support import _send as _send

from datetime import timedelta

from yoke_core.domain.session_message_service import send_message

from yoke_core.domain.session_message_wake import wake_eligible_recipients

from yoke_core.domain.session_native_turn_end import (
    apply_native_turn_ends,
    probe_targets,
)

from runtime.api.domain.session_message_support_test_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)

MACHINE_ID = "22222222-2222-4222-8222-222222222222"

CODEX_VERSION = "0.150.0-alpha.8"

CLAUDE_VERSION = "2.1.238"

STALE_ACTIVITY = (NOW - timedelta(minutes=120)).isoformat().replace("+00:00", "Z")

LATER = NOW + timedelta(minutes=11)

OBSERVED_AT = (NOW - timedelta(minutes=100)).isoformat().replace("+00:00", "Z")

EVIDENCE = {
    "record": "codex_rollout_tail",
    "turn_id": "turn-1",
    "codex_error_info": "server_overloaded",
    "error_message": "Selected model is at capacity.",
}


def _codex_connection(*, surface: str = "codex-cli", machine_id: str = MACHINE_ID):
    """A quiet codex session whose turn ended with no hook to say so."""
    conn = message_connection()
    codex = surface.startswith("codex-")
    conn.execute(
        "UPDATE harness_sessions SET executor=?,executor_surface=?,"
        "executor_version=?,machine_id=?,last_heartbeat=?,last_tool_call_at=?,"
        "turn_posture='running' WHERE session_id='s2'",
        (
            "codex" if codex else "claude-code",
            surface,
            CODEX_VERSION if codex else CLAUDE_VERSION,
            machine_id,
            STALE_ACTIVITY,
            STALE_ACTIVITY,
        ),
    )
    conn.commit()
    return conn


def _targets(conn, *, machine_id: str = MACHINE_ID, projects=(1,)):
    return probe_targets(
        conn, machine_id=machine_id, authorized_projects=projects, now=LATER
    )


def _pending(conn) -> list[dict[str, str]]:
    """Send, run the wake sweep, and return the native turn probe targets."""
    _send(conn)
    wake_eligible_recipients(conn, now=LATER)
    return _targets(conn)


def _apply(conn, session_id: str = "s2", *, machine_id: str = MACHINE_ID, **overrides):
    report = {
        "session_id": session_id,
        "observed_at": OBSERVED_AT,
        "evidence": EVIDENCE,
    }
    report.update(overrides)
    return apply_native_turn_ends(
        conn,
        machine_id=machine_id,
        authorized_projects=(1,),
        reports=[report],
    )


def _posture(conn, session_id: str = "s2") -> str:
    return conn.execute(
        "SELECT turn_posture FROM harness_sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()["turn_posture"]
