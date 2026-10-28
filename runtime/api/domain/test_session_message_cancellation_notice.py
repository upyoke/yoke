"""Cleanup tells the original sender when pending mail cannot be delivered."""

from __future__ import annotations

import pytest

from runtime.api.test_sessions import _register
from runtime.api.domain.test_session_process_liveness_report import _ghost, _apply
from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.actor_permissions import (
    ROLE_OPERATOR,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.session_message_cancellation_notice import (
    notify_cancelled_message_senders,
)
from yoke_core.domain.sessions_render_reclaim import (
    pending_message_senders,
    reclaim_stale_session,
)


@pytest.fixture
def conn(test_db):
    return test_db


def _seed(conn, *, sender="sender", state="pending"):
    actor_id = conn.execute(
        "INSERT INTO actors (kind,name,created_at) VALUES (%s,%s,%s) RETURNING id",
        ("human", "Message sender", utc_now()),
    ).fetchone()[0]
    seed_roles_and_permissions(conn)
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=1,
        role_name=ROLE_OPERATOR,
    )
    _register(conn, session_id="sender", actor_id=actor_id)
    recipient = _ghost(conn)
    message = send_message(
        conn,
        actor_id=actor_id,
        sender_session_id=sender,
        selector=RecipientSelector(session_ids=[recipient]),
        body="Please inspect.",
    )["message_id"]
    conn.execute(
        "UPDATE session_message_recipients SET state=%s "
        "WHERE message_id=%s AND session_id=%s",
        (state, message, recipient),
    )
    conn.commit()
    return message, recipient


def _notices(conn):
    return conn.execute(
        "SELECT m.* FROM session_messages m JOIN session_message_recipients r "
        "ON m.message_id=r.message_id WHERE r.session_id='sender'"
    ).fetchall()


@pytest.mark.parametrize("cleanup", ["reclaim", "process_death"])
@pytest.mark.parametrize("state", ["pending", "injected", "acknowledged"])
def test_cleanup_only_notifies_for_undelivered_mail(conn, cleanup, state):
    message, recipient = _seed(conn, state=state)
    pending = pending_message_senders(conn, recipient)
    conn.commit()
    if cleanup == "reclaim":
        reclaim_stale_session(conn, recipient)
        reason = "session_reclaimed"
    else:
        assert _apply(conn, recipient)["ended"] == [recipient]
        reason = "process_verified_dead"
    receipt = conn.execute(
        "SELECT state FROM session_message_recipients "
        "WHERE message_id=%s AND session_id=%s",
        (message, recipient),
    ).fetchone()
    assert receipt["state"] == (
        "acknowledged" if state == "acknowledged" else "cancelled"
    )
    notices = _notices(conn)
    assert len(notices) == (1 if state == "pending" else 0)
    if notices:
        notice = notices[0]
        assert message in notice["body"]
        assert recipient in notice["body"]
        assert reason in notice["body"]
        assert "Address the person separately" in notice["body"]
        assert notice["sender_session_id"] is None
        # Repeating post-commit work must preserve one durable notice row.
        notify_cancelled_message_senders(
            conn,
            pending,
            session_id=recipient,
            reason=reason,
        )
        assert len(_notices(conn)) == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM session_message_recipients WHERE message_id=%s",
                (message,),
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("cleanup", ["reclaim", "process_death"])
def test_engine_mail_without_sender_session_needs_no_notice(conn, cleanup):
    _, recipient = _seed(conn, sender=None)
    if cleanup == "reclaim":
        reclaim_stale_session(conn, recipient)
    else:
        assert _apply(conn, recipient)["ended"] == [recipient]
    assert not _notices(conn)


@pytest.mark.parametrize("cleanup", ["reclaim", "process_death"])
def test_notice_failure_never_undoes_committed_cleanup(
    conn,
    monkeypatch,
    caplog,
    cleanup,
):
    message, recipient = _seed(conn)

    def fail_notice(connection, **kwargs):
        receipt = connection.execute(
            "SELECT state FROM session_message_recipients "
            "WHERE message_id=%s AND session_id=%s",
            (message, recipient),
        ).fetchone()
        assert receipt["state"] == "cancelled"
        assert (
            connection.execute(
                "SELECT ended_at FROM harness_sessions WHERE session_id=%s",
                (recipient,),
            ).fetchone()["ended_at"]
            is not None
        )
        raise RuntimeError("notice service unavailable")

    monkeypatch.setattr(
        "yoke_core.domain.session_message_service.send_message",
        fail_notice,
    )
    if cleanup == "reclaim":
        reclaim_stale_session(conn, recipient)
    else:
        assert _apply(conn, recipient)["ended"] == [recipient]
    assert "message_cancellation_notice_failed" in caplog.text
    assert message in caplog.text
    assert not _notices(conn)
