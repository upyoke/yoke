"""Org message administration and original-sender notice identity boundaries."""

from datetime import timedelta

import pytest

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain import actor_permissions as permissions
from yoke_core.domain.session_message_receipts import cancel_message
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import message_details
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_wake_failure_notice import notify_failed_wake
from runtime.api.domain.test_session_org_messages import (
    NOW,
    engine_notice,
    org_world as org_world,
    send,
)


def test_foreign_human_sender_session_refuses_before_message_mutation(org_world):
    w = org_world
    with pytest.raises(SessionMessageError) as error:
        send(w, sender="foreign-target")
    assert error.value.code == "sender_session_forbidden"
    assert w.conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0
    assert (
        w.conn.execute("SELECT COUNT(*) FROM session_message_recipients").fetchone()[0]
        == 0
    )


def test_org_admin_can_cancel_engine_message(org_world):
    w = org_world
    mid = engine_notice(w)[0]["message_id"]
    with pytest.raises(SessionMessageError) as error:
        cancel_message(w.conn, message_id=mid, actor_id=w.operator, now=NOW)
    assert error.value.code == "cancel_forbidden"
    permissions.grant_actor_org_role(
        w.conn, actor_id=w.operator, org_id=w.org, role_name="admin"
    )
    cancelled = cancel_message(w.conn, message_id=mid, actor_id=w.operator, now=NOW)
    assert cancelled["cancellation_reason"] == "cancelled_by_org_admin"
    assert cancelled["recipients"][0]["state"] == "cancelled"


def test_project_admin_cannot_cancel_mixed_org_fanout(org_world):
    w = org_world
    mid = send(w, ("org-target", "project-target"))["message_id"]
    permissions.grant_actor_project_role(
        w.conn, actor_id=w.reader, project_id=1, role_name="owner"
    )
    with pytest.raises(SessionMessageError) as error:
        cancel_message(w.conn, message_id=mid, actor_id=w.reader, now=NOW)
    assert error.value.code == "cancel_forbidden"
    assert {r["state"] for r in message_details(w.conn, mid)["recipients"]} == {
        "pending"
    }


def failed_notice(world, message_id):
    conn = world.conn
    conn.execute(
        "INSERT INTO session_message_attempts(attempt_id,message_id,target_session_id,"
        "attempt_kind,started_at,completed_at,result_code) "
        "VALUES ('failed',%s,'org-target','wake_relay',%s,%s,'failed')",
        (message_id, NOW, NOW + timedelta(seconds=1)),
    )
    row = dict(
        conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id='org-target'"
        ).fetchone()
    )
    notice = notify_failed_wake(
        conn,
        dict(row, message_id=message_id),
        now=NOW + timedelta(seconds=1),
        max_attempts=3,
    )
    assert notice is not None
    return message_details(conn, notice)


def test_failed_org_wake_returns_to_authenticated_original_org_sender(org_world):
    w = org_world
    notice = failed_notice(w, send(w)["message_id"])
    assert [row["session_id"] for row in notice["recipients"]] == ["org-sender"]
    assert [row["actor_id"] for row in notice["actor_recipients"]] == [w.owner]
    assert notice["recipients"][0]["project_id"] is None
    assert notice["recipients"][0]["org_id"] == w.org
    assert "steering_recipient" not in notice


@pytest.mark.parametrize("sender_session", [None, "org-sender", "org-target"])
def test_engine_provenance_never_becomes_a_session_notice_route(
    org_world, sender_session
):
    w = org_world
    mid = engine_notice(w, sender_session_id=sender_session)[0]["message_id"]
    notice = failed_notice(w, mid)
    assert not notice["recipients"]
    assert [row["actor_id"] for row in notice["actor_recipients"]] == [w.owner]
    assert "steering_recipient" not in notice


def test_unauthorized_org_target_refuses_without_hidden_recipient(org_world):
    w = org_world
    with pytest.raises(SessionMessageError) as error:
        send_message(
            w.conn,
            actor_id=w.reader,
            sender_session_id="foreign-target",
            selector=RecipientSelector(session_ids=["org-target"]),
            body="Please inspect this result.",
            now=NOW,
        )
    assert error.value.code == "zero_recipients"
    with pytest.raises(SessionMessageError) as unknown:
        send_message(
            w.conn,
            actor_id=w.reader,
            sender_session_id="foreign-target",
            selector=RecipientSelector(session_ids=["missing"]),
            body="Please inspect this result.",
            now=NOW,
        )
    assert unknown.value.code == error.value.code
    assert str(error.value).replace("org-target", "missing") == str(unknown.value)
    assert w.conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0
