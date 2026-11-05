"""A session whose native turn ended is reclassified and becomes wakeable."""

from __future__ import annotations

from runtime.api.domain.session_native_turn_end_test_support import (CLAUDE_VERSION as CLAUDE_VERSION, CODEX_VERSION as CODEX_VERSION, EVIDENCE as EVIDENCE, LATER as LATER, MACHINE_ID as MACHINE_ID, NOW as NOW, OBSERVED_AT as OBSERVED_AT, STALE_ACTIVITY as STALE_ACTIVITY, _apply as _apply, _codex_connection as _codex_connection, _pending as _pending, _posture as _posture, _targets as _targets)
from runtime.api.domain.session_message_machine_wake_route_test_support import (_send as _send)


from yoke_core.domain.session_message_wake import wake_eligible_recipients
from runtime.api.domain.session_message_support_test_support import (
    NOW_TEXT,
)


def _release_claims(conn, session_id: str = "s2") -> None:
    """Drop the fixture's work claim so only the refused-wake set can match."""
    conn.execute(
        "UPDATE work_claims SET released_at=? WHERE session_id=?",
        (NOW_TEXT, session_id),
    )
    conn.commit()


def test_a_recorded_refused_wake_names_its_session_for_a_turn_record_read():
    conn = _codex_connection()
    _release_claims(conn)
    message_id = _send(conn)
    # A stored operation refusal remains a reason to inspect the native record.
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,"
        "completed_at,result_code) VALUES ('refused',?,'s2','wake_relay',?,?,'skipped_operation')",
        (message_id, NOW_TEXT, NOW_TEXT),
    )
    conn.commit()
    assert _targets(conn) == [{"session_id": "s2", "executor_surface": "codex-cli"}]


def test_a_live_claim_holder_is_read_back_with_nothing_pending():
    """The case that cost twenty minutes: no envelope, so no refused wake."""
    conn = _codex_connection()
    assert _targets(conn) == [{"session_id": "s2", "executor_surface": "codex-cli"}]


def test_a_session_holding_nothing_and_owed_no_wake_is_never_read_back():
    conn = _codex_connection()
    _release_claims(conn)
    assert _targets(conn) == []


def test_a_surface_that_reports_its_own_turn_end_is_never_read_back():
    conn = _codex_connection(surface="claude-cli")
    _send(conn)
    assert _targets(conn) == []


def test_targets_are_scoped_to_the_asking_machine_and_its_projects():
    conn = _codex_connection()
    _pending(conn)
    other_machine = "33333333-3333-4333-8333-333333333333"
    assert _targets(conn, machine_id=other_machine) == []
    assert _targets(conn, projects=(2,)) == []


def test_an_observed_turn_end_stamps_the_posture_the_missing_hook_would_have():
    conn = _codex_connection()
    _pending(conn)

    assert _apply(conn) == {"reclassified": ["s2"], "skipped": []}
    assert _posture(conn) == "waiting"


def test_a_reclassified_session_becomes_wake_eligible_through_its_one_route():
    conn = _codex_connection()
    _pending(conn)
    _apply(conn)

    eligible = wake_eligible_recipients(conn, now=LATER)

    assert [row["session_id"] for row in eligible] == ["s2"]
    assert eligible[0]["wake_mode"] == "waiting"
    assert eligible[0]["turn_posture"] == "waiting"
    # Nothing is left to probe once the session is reachable again.
    assert _targets(conn) == []


def test_a_newer_turn_keeps_running_and_the_report_is_named_superseded():
    conn = _codex_connection()
    _pending(conn)
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
    _pending(conn)
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
