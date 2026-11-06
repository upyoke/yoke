"""Session mentions resolve the same current title at every read surface."""

from yoke_core.domain import session_display
from yoke_core.domain.decision_request_requester_label import requester_labels
from yoke_core.domain.session_message_display import project_session_names
from yoke_core.domain.session_message_list_row import message_list_row
from yoke_core.domain.steering_fleet_report_labels import label_text
from runtime.api.domain.session_message_support_test_support import message_connection, NOW


def test_human_title_holds_and_read_time_rename(monkeypatch):
    conn = message_connection()
    monkeypatch.setattr(session_display, "utc_now", lambda: NOW)
    conn.execute(
        "UPDATE harness_sessions SET harness_title='[PILLS]',executor_surface='claude-desktop' WHERE session_id='s1'"
    )
    expected = (
        "[PILLS] · claude-desktop · alpha · holds ALP-1 'Test work' · last tool 0s ago"
    )
    assert session_display.session_display_names(conn, ["s1"]) == {"s1": expected}
    assert requester_labels(conn, ["s1"])["s1"] == expected
    message = {"message_id": "message", "sender_session_id": "s1", "body": "Hello"}
    project_session_names(conn, [message])
    assert message_list_row(message)["sender"] == expected
    assert (
        label_text("Session s1; `yoke say --session s1`", {"s1": expected})
        == f"Session {expected}; `yoke say --session s1`"
    )
    notice = {"idempotency_key": "desktop-operator-wake:message:s1"}
    project_session_names(conn, [notice])
    assert expected in notice["body"]
    assert "s1" not in notice["body"]
    conn.execute(
        "UPDATE harness_sessions SET harness_title='New name' WHERE session_id='s1'"
    )
    project_session_names(conn, [notice])
    assert "New name" in notice["body"]
    assert "[PILLS]" not in notice["body"]


def test_launched_item_title_and_most_recent_released_claim(monkeypatch):
    conn = message_connection()
    monkeypatch.setattr(session_display, "utc_now", lambda: NOW)
    conn.execute(
        "INSERT INTO session_messages(message_id,body,body_sha256,selector_snapshot,created_at,expires_at) VALUES ('mandate','Work','hash','{}',?,?)",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO session_launches(launch_id,requester_actor_id,project_id,requested_surface,selected_surface,message_id,item_id,state,deadline_at,created_at,registered_session_id) VALUES ('launch',10,1,'codex-cli','codex-cli','mandate',101,'succeeded',?,?,'s1')",
        (NOW, NOW),
    )
    label = session_display.session_display_names(conn, ["s1"])["s1"]
    assert label.startswith("ALP-1 Test work · codex-desktop · alpha · holds ALP-1")
    conn.execute("UPDATE work_claims SET released_at=? WHERE session_id='s1'", (NOW,))
    assert (
        " · held ALP-1 · " in session_display.session_display_names(conn, ["s1"])["s1"]
    )


def test_roster_and_summary_expose_labels_without_changing_identity():
    from yoke_core.domain.session_control_roster import session_control_roster_result
    from yoke_core.domain.sessions_list_read import session_summary_result
    from runtime.api.domain.session_control_roster_test_support import (
        _connection,
        _add_session,
        _base_row,
        NOW,
    )

    conn = _connection()
    _add_session(conn, surface="codex-vscode", version="0.148.0-alpha.15")
    base = _base_row(surface="codex-vscode", liveness="active")
    base.update(
        harness_title="Chat title", display_label="Chat title · codex-vscode · yoke"
    )
    result = session_control_roster_result([base], conn=conn, now=NOW)
    assert {"harness_title", "display_label"} <= set(result["fields"])
    assert result["rows"][0]["harness_title"] == "Chat title"
    assert result["rows"][0]["display_label"] == base["display_label"]
    summary = session_summary_result(result["rows"], offset=0, limit=25)
    assert summary["rows"][0]["display_label"] == base["display_label"]
    assert summary["rows"][0]["session_id"] == base["session_id"]


def test_label_uses_tool_clock_even_when_gone_process_has_fresh_heartbeat(monkeypatch):
    conn = message_connection()
    monkeypatch.setattr(session_display, "utc_now", lambda: NOW)
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at='2026-08-22T15:00:00Z', "
        "native_process_gone_at='2026-08-22T15:30:00Z' WHERE session_id='s1'"
    )
    label = session_display.session_display_name(conn, "s1")
    assert "last tool 1h ago" in label
    assert "0s ago" not in label
    assert "active " not in label
    conn.execute("UPDATE harness_sessions SET last_tool_call_at=NULL WHERE session_id='s1'")
    assert "last tool" not in session_display.session_display_name(conn, "s1")
    conn.close()
