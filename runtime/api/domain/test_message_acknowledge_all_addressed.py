"""The registered acknowledgement settles only the caller's addressed receipts."""

import pytest

from runtime.api.domain.test_actor_session_messages import _members
from runtime.api.domain.test_session_message_handlers import _request
from runtime.api.domain.test_session_message_support import NOW, selector
from yoke_core.domain import session_message_receipts
from yoke_core.domain.actor_message_recipients import inbox_actor_messages
from yoke_core.domain.handlers import session_messages_receipts
from yoke_core.domain.session_message_service import send_message


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    from yoke_core.domain import actor_message_recipients

    monkeypatch.setattr(actor_message_recipients, "utc_now", lambda: NOW)


class OpenConnection:
    def __init__(self, conn, message_id):
        self._inner, self.message_id, self.commits = conn, message_id, []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass

    def states(self):
        return (
            self._inner.execute(
                "SELECT state FROM session_message_recipients WHERE message_id=?",
                (self.message_id,),
            ).fetchone()[0],
            self._inner.execute(
                "SELECT state FROM actor_message_recipients "
                "WHERE message_id=? AND actor_id=10",
                (self.message_id,),
            ).fetchone()[0],
        )

    def commit(self):
        self.commits.append(self.states())
        self._inner.commit()


def _ack(conn, message_id, monkeypatch, *, session_id="s1"):
    monkeypatch.setattr(session_messages_receipts, "open_connection", lambda: conn)
    monkeypatch.setattr(session_message_receipts, "utc_now", lambda: NOW)
    return session_messages_receipts.handle_message_acknowledge(
        _request(
            "session_control.message.acknowledge",
            {"message_id": message_id},
            session_id=session_id,
        )
    )


def _send(conn, **anchors):
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(**anchors),
        body="Read the addressed work.",
        now=NOW,
    )["message_id"]


def test_handler_settles_both_caller_receipts_in_one_commit(monkeypatch):
    conn = _members()
    message_id = _send(conn, session_ids=["s1"], actors=["10"])
    observed = OpenConnection(conn, message_id)
    assert (
        inbox_actor_messages(conn, actor_id=10, include_read=False)["pending_count"]
        == 1
    )
    outcome = _ack(observed, message_id, monkeypatch)
    assert outcome.primary_success
    assert observed.states() == ("acknowledged", "read")
    assert all(
        states in (("pending", "pending"), ("acknowledged", "read"))
        for states in observed.commits
    )
    assert (
        inbox_actor_messages(conn, actor_id=10, include_read=False)["pending_count"]
        == 0
    )
    assert _ack(observed, message_id, monkeypatch).primary_success


def test_handler_repairs_actor_receipt_after_prior_session_ack(monkeypatch):
    conn = _members()
    message_id = _send(conn, session_ids=["s1"], actors=["10"])
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged',acknowledged_at=? "
        "WHERE message_id=?",
        (NOW.isoformat(), message_id),
    )
    conn.commit()
    assert _ack(
        OpenConnectionWithoutTrace(conn), message_id, monkeypatch
    ).primary_success
    assert (
        inbox_actor_messages(conn, actor_id=10, include_read=False)["pending_count"]
        == 0
    )


def test_actor_failure_rolls_back_session_acknowledgement(monkeypatch):
    conn = _members()
    message_id = _send(conn, session_ids=["s1"], actors=["10"])
    observed = OpenConnection(conn, message_id)

    def fail(*args, **kwargs):
        raise RuntimeError("receipt write failed")

    monkeypatch.setattr(session_message_receipts, "acknowledge_actor_recipient", fail)
    outcome = _ack(observed, message_id, monkeypatch)
    assert not outcome.primary_success
    assert observed.states() == ("pending", "pending")


@pytest.mark.parametrize("anchors", [{"session_ids": ["s1"]}, {"actors": ["10"]}])
def test_handler_still_accepts_a_single_addressed_kind(anchors, monkeypatch):
    conn = _members()
    message_id = _send(conn, **anchors)
    assert _ack(
        OpenConnectionWithoutTrace(conn), message_id, monkeypatch
    ).primary_success


class OpenConnectionWithoutTrace:
    def __init__(self, conn):
        self._inner = conn

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass


def test_session_ack_never_settles_another_addressed_actor(monkeypatch):
    conn = _members()
    message_id = _send(conn, session_ids=["s1"], actors=["11"])
    assert _ack(
        OpenConnectionWithoutTrace(conn), message_id, monkeypatch
    ).primary_success
    assert (
        conn.execute(
            "SELECT state FROM actor_message_recipients WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        == "pending"
    )


def test_unaddressed_session_and_actor_are_still_refused(monkeypatch):
    conn = _members()
    message_id = _send(conn, session_ids=["s2"], actors=["11"])
    outcome = _ack(OpenConnectionWithoutTrace(conn), message_id, monkeypatch)
    assert not outcome.primary_success
    assert outcome.error.code == "acknowledge_self_only"
    assert (
        conn.execute(
            "SELECT state FROM actor_message_recipients WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        == "pending"
    )
