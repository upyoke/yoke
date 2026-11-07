"""Session state filters and CLI/web parity across pagination."""

from runtime.api.domain.handlers.sessions_list_handler_test_support import (
    _insert_session,
    _iso,
    _request,
)
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_contracts.session_state_fields import session_state_columns


def test_status_filter_precedes_limit_and_offset(test_db):
    _insert_session(test_db, "silent", last_heartbeat=_iso(30))
    for name in ("first", "second", "third"):
        _insert_session(test_db, name, last_heartbeat=_iso(), last_tool_call_at=_iso())
    rows = list_sessions(status="waiting", limit=1)
    assert [row["session_id"] for row in rows] == ["silent"]
    assert list_sessions(status="waiting", limit=1, offset=1) == []


def test_summary_and_full_reads_have_identical_state(test_db):
    _insert_session(test_db, "between", last_heartbeat=_iso(), last_tool_call_at=_iso())
    test_db.execute(
        "UPDATE harness_sessions SET turn_posture='waiting' WHERE session_id='between'"
    )
    test_db.commit()
    full = handle_sessions_list(_request({"session_id": "between"})).result_payload[
        "rows"
    ][0]
    summary = handle_sessions_list(
        _request({"session_id": "between", "detail": "summary"})
    ).result_payload["rows"][0]
    assert session_state_columns(full) == session_state_columns(summary)
    assert summary["status"] == "waiting"
    assert full["session_state"]["activity"] == "between_turns"
    assert full["session_state"]["intent"]["state"] == "none"


def test_removed_selector_names_upgrade_floor():
    outcome = handle_sessions_list(_request({"liveness": "active"}))
    assert not outcome.primary_success
    assert outcome.error.code == "function_version_skew"
    assert "required client floor" in outcome.error.message
    assert "--status" in outcome.error.message


def test_frontier_and_roster_share_project_idle_and_open_call_facts(test_db):
    from datetime import timedelta
    from runtime.api.conftest import insert_item
    from runtime.api.domain.handlers.sessions_list_handler_test_support import _insert_item_claim
    from runtime.api.domain.handlers.items_read_test_support import request_for
    from yoke_core.domain.handlers.item_page_reads import handle_items_overview_list
    from yoke_core.domain.project_policy_capabilities import set_project_policy_value
    from yoke_contracts.timestamps import utc_now

    now = utc_now()
    insert_item(test_db, id=19441, title="Status parity", status="implementing")
    _insert_session(test_db, "status-holder", last_heartbeat=now - timedelta(minutes=10),
                    last_tool_call_at=now - timedelta(minutes=10))
    _insert_item_claim(test_db, "status-holder", 19441)
    test_db.execute("UPDATE harness_sessions SET turn_posture='running', native_process_gone_at=%s WHERE session_id='status-holder'", (now,))
    for minutes, expected in [(5, "waiting"), (15, "working")]:
        set_project_policy_value(test_db, 1, "session_idle_minutes", minutes)
        test_db.commit()
        roster = list_sessions(session_id="status-holder")[0]
        overview = handle_items_overview_list(request_for("items.overview.list", {"relevance": "overview"}))
        item = next(row for row in overview.result_payload["rows"] if row["title"] == "Status parity")
        assert roster["status"] == expected
        assert item["frontier_group"]["activity"] == expected

    set_project_policy_value(test_db, 1, "session_idle_minutes", 5)
    test_db.execute(
        "INSERT INTO session_tool_calls (session_id,tool_use_id,tool_name,started_at) "
        "VALUES ('status-holder','status-watch','Bash',%s)",
        (now - timedelta(minutes=10),),
    )
    test_db.commit()
    roster = list_sessions(session_id="status-holder")[0]
    overview = handle_items_overview_list(request_for("items.overview.list", {"relevance": "overview"}))
    item = next(row for row in overview.result_payload["rows"] if row["title"] == "Status parity")
    assert roster["status"] == "working"
    assert item["frontier_group"]["activity"] == "working"
