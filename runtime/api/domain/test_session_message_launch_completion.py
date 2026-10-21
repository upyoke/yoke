"""Launch convergence makes queued item mail wakeable without another hook."""

from runtime.api.domain.test_session_message_launch_queue import (
    world,
    send,
    register,
    claim,
)
from runtime.api.domain.test_session_message_support import NOW, NOW_TEXT
from yoke_core.domain.session_launch_registration import complete_launch_for_message
from yoke_core.domain.session_message_store import message_details


def test_claimed_launch_completion_binds_mail_before_any_further_hook(monkeypatch):
    conn = world(monkeypatch)
    sent = send(conn)
    register(conn)
    claim(conn)
    conn.execute("UPDATE session_launches SET launching_at=?", (NOW_TEXT,))
    conn.execute(
        "INSERT INTO session_message_recipients(message_id,session_id,project_id,"
        "resolution_evidence,routing_snapshot,state,created_at,wake_after) "
        "VALUES ('mandate','s4',1,'[]','{}','acknowledged',?,?)",
        (NOW_TEXT, NOW_TEXT),
    )
    conn.commit()
    completed = complete_launch_for_message(
        conn,
        message_id="mandate",
        session_id="s4",
        now=NOW,
    )
    assert completed.state == "succeeded"
    receipts = message_details(conn, sent["message_id"])["recipients"]
    assert len(receipts) == 1
    assert receipts[0]["session_id"] == "s4"
    assert receipts[0]["state"] == "pending"
