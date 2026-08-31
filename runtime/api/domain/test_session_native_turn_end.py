"""A session whose native turn ended is reclassified and becomes wakeable."""

from __future__ import annotations

from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_native_turn_end import (
    apply_native_turn_ends,
    probe_targets,
)
from runtime.api.domain.test_session_message_support import (
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


def _send(conn) -> str:
    return str(
        send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(session_ids=["s2"]),
            body="Body stays server-side through every wake route.",
            now=NOW,
        )["message_id"]
    )


def _targets(conn, *, machine_id: str = MACHINE_ID, projects=(1,)):
    return probe_targets(
        conn, machine_id=machine_id, authorized_projects=projects, now=LATER
    )


def _stuck(conn) -> list[dict[str, str]]:
    """Send, let the wake sweep refuse it, and return the probe targets."""
    _send(conn)
    assert wake_eligible_recipients(conn, now=LATER) == []
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


def test_a_refused_wake_names_its_session_for_a_turn_record_read():
    conn = _codex_connection()
    assert _stuck(conn) == [{"session_id": "s2", "executor_surface": "codex-cli"}]


def test_a_session_with_no_refused_wake_is_never_read_back():
    conn = _codex_connection()
    _send(conn)
    assert _targets(conn) == []


def test_a_surface_that_reports_its_own_turn_end_is_never_read_back():
    conn = _codex_connection(surface="claude-cli")
    _send(conn)
    assert _targets(conn) == []


def test_targets_are_scoped_to_the_asking_machine_and_its_projects():
    conn = _codex_connection()
    _stuck(conn)
    other_machine = "33333333-3333-4333-8333-333333333333"
    assert _targets(conn, machine_id=other_machine) == []
    assert _targets(conn, projects=(2,)) == []


def test_an_observed_turn_end_stamps_the_posture_the_missing_hook_would_have():
    conn = _codex_connection()
    _stuck(conn)

    assert _apply(conn) == {"reclassified": ["s2"], "skipped": []}
    assert _posture(conn) == "waiting"


def test_a_reclassified_session_becomes_wake_eligible_through_its_one_route():
    conn = _codex_connection()
    _stuck(conn)
    _apply(conn)

    eligible = wake_eligible_recipients(conn, now=LATER)

    assert [row["session_id"] for row in eligible] == ["s2"]
    assert eligible[0]["wake_mode"] == "waiting"
    assert eligible[0]["turn_posture"] == "waiting"
    # Nothing is left to probe once the session is reachable again.
    assert _targets(conn) == []


def test_a_newer_turn_keeps_running_and_the_report_is_named_superseded():
    conn = _codex_connection()
    _stuck(conn)
    conn.execute(
        "UPDATE harness_sessions SET turn_posture_at=? WHERE session_id='s2'",
        (NOW_TEXT,),
    )
    conn.commit()

    assert _apply(conn) == {
        "reclassified": [],
        "skipped": [{"session_id": "s2", "status": "posture_superseded"}],
    }
    assert _posture(conn) == "running"


def test_a_report_from_the_wrong_machine_is_refused_by_name():
    conn = _codex_connection()
    _stuck(conn)
    other_machine = "33333333-3333-4333-8333-333333333333"

    assert _apply(conn, machine_id=other_machine)["skipped"] == [
        {"session_id": "s2", "status": "machine_mismatch"}
    ]
    assert _posture(conn) == "running"


def test_a_report_about_an_unknown_session_is_refused_by_name():
    conn = _codex_connection()
    assert _apply(conn, session_id="absent")["skipped"] == [
        {"session_id": "absent", "status": "session_not_found"}
    ]


def test_a_report_about_a_hook_reporting_surface_is_refused_by_name():
    conn = _codex_connection(surface="claude-cli")
    assert _apply(conn)["skipped"] == [
        {"session_id": "s2", "status": "surface_without_turn_record"}
    ]


def test_a_report_about_an_ended_session_is_refused_by_name():
    conn = _codex_connection()
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id='s2'", (NOW_TEXT,)
    )
    conn.commit()

    assert _apply(conn)["skipped"] == [
        {"session_id": "s2", "status": "session_terminal"}
    ]
