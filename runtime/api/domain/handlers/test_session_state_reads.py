"""Session state filters and CLI/web parity across pagination."""

from runtime.api.domain.handlers.sessions_list_handler_test_support import (
    _insert_session, _iso, _request,
)
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_contracts.session_state_fields import session_state_columns


def test_activity_filter_precedes_limit_and_offset(test_db):
    _insert_session(test_db, "silent", last_heartbeat=_iso(20))
    for name in ("first", "second", "third"):
        _insert_session(test_db, name, last_heartbeat=_iso(), last_tool_call_at=_iso())
    rows = list_sessions(activity="silent", limit=1)
    assert [row["session_id"] for row in rows] == ["silent"]
    assert list_sessions(activity="silent", limit=1, offset=1) == []


def test_summary_and_full_reads_have_identical_state(test_db):
    _insert_session(test_db, "between", last_heartbeat=_iso(), last_tool_call_at=_iso())
    test_db.execute("UPDATE harness_sessions SET turn_posture='waiting' WHERE session_id='between'")
    test_db.commit()
    full = handle_sessions_list(_request({"session_id": "between"})).result_payload["rows"][0]
    summary = handle_sessions_list(_request({"session_id": "between", "detail": "summary"})).result_payload["rows"][0]
    assert session_state_columns(full) == session_state_columns(summary)
    assert summary["presence"] == "present"
    assert summary["activity"] == "between_turns"
    assert summary["intent"]["state"] == "none"


def test_removed_selector_names_upgrade_floor():
    outcome = handle_sessions_list(_request({"liveness": "active"}))
    assert not outcome.primary_success
    assert outcome.error.code == "function_version_skew"
    assert "required client floor" in outcome.error.message
    assert "--presence" in outcome.error.message
