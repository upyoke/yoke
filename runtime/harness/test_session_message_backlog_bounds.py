"""Long-session proof that a receipt is injected only when its body ships.

Every test here drives the whole path a live hook drives — durable lease,
render, harness composition, settlement — because the defect this file
guards against lives in the seam between them: a lease may carry more
messages than the composed reply ends up carrying, and settling the lease
as injected then issues receipts for bodies no model ever saw.
"""

from __future__ import annotations

import pytest

from yoke_contracts.hook_context_compose import POINTER_BEGIN
from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    lease_for_hook,
)
from yoke_core.domain.session_message_queries import list_messages
from yoke_core.domain.session_message_service import send_message
from yoke_core.hooks import session_message_delivery as hook_delivery
from yoke_core.hooks.decision_render import render_claude_decision
from yoke_core.hooks.session_message_delivery_port import (
    LeasedSessionMessage,
    SessionMessageLease,
)
from yoke_core.hooks.types import HookContext
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


RECIPIENT = "s2"
SENDER = "s1"
EVENTS = ("PreToolUse", "PostToolUse")


@pytest.fixture(autouse=True)
def _fixed_message_clock(monkeypatch) -> None:
    from yoke_core.domain import session_message_delivery

    monkeypatch.setattr(session_message_delivery, "utc_now", lambda: NOW)


@pytest.fixture(autouse=True)
def _isolated_watcher_discovery(monkeypatch) -> None:
    """Channel routing is independent of this machine's watcher processes."""
    monkeypatch.setattr(
        "yoke_core.hooks.fleet_watcher_presence.list_process_cmdlines", lambda: ()
    )


class _ConnectionPort:
    """The durable delivery port, bound to one test connection."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def read_for_hook(self, *, session_id: str, hook_event: str, limit: int):
        raise AssertionError("the parent path never reads a child view")

    def lease_for_hook(
        self, *, session_id: str, hook_event: str, limit: int
    ) -> SessionMessageLease | None:
        raw = lease_for_hook(
            self.conn, session_id=session_id, hook_event=hook_event, limit=limit
        )
        if raw is None:
            return None
        return SessionMessageLease(
            lease_id=raw["lease_id"],
            messages=tuple(
                LeasedSessionMessage(
                    message_id=row["message_id"],
                    body=row["body"],
                    sender_actor_id=row["sender_actor_id"],
                )
                for row in raw["messages"]
            ),
            remaining_count=raw["remaining_count"],
        )

    def complete_hook_lease(
        self, *, lease_id: str, injected: bool, result: str
    ) -> None:
        complete_hook_lease(
            self.conn, lease_id=lease_id, injected=injected, result=result
        )

    def confirm_report_delivered(self, **_fields: str) -> None:
        return None

    def probe_undelivered(
        self, *, session_id: str, hook_event: str, reason: str, detail: str = ""
    ) -> int:
        return 0


def _hook(conn, monkeypatch, event: str = "PreToolUse") -> str:
    """Run one model-visible hook end to end and return its reply text."""
    port = _ConnectionPort(conn)
    monkeypatch.setattr(hook_delivery, "_delivery_port", lambda: port)
    decision = hook_delivery.evaluate(
        HookContext(
            event_name=event,
            executor_family="claude",
            executor_surface="claude-cli",
            payload={},
            session_id=RECIPIENT,
            now=NOW,
        )
    )
    rendered, _exit_code = render_claude_decision([decision], event)
    hook_delivery.settle_after_render(
        [decision], rendered_text=rendered, denied=False, port=port
    )
    return rendered


def _send(conn, count: int, *, body: str) -> list[str]:
    return [
        send_message(
            conn,
            actor_id=10,
            sender_session_id=SENDER,
            selector=selector(session_ids=[RECIPIENT]),
            body=f"message {index}: {body}",
            now=NOW,
        )["message_id"]
        for index in range(count)
    ]


def _receipts(conn) -> dict[str, str]:
    rows = conn.execute(
        "SELECT message_id,state FROM session_message_recipients "
        f"WHERE session_id='{RECIPIENT}'"
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _attempt_results(conn) -> set[str]:
    rows = conn.execute(
        "SELECT result_code FROM session_message_attempts WHERE completed_at IS NOT NULL"
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_a_four_message_backlog_ships_every_body_it_settles() -> None:
    conn = message_connection()
    message_ids = _send(conn, 4, body="please re-run the focused verifier")

    with pytest.MonkeyPatch.context() as monkeypatch:
        rendered = _hook(conn, monkeypatch)

        assert all(message_id in rendered for message_id in message_ids)
        assert set(_receipts(conn).values()) == {"injected"}
        assert _hook(conn, monkeypatch, "PostToolUse") == ""


def test_a_backlog_is_not_truncated_by_a_message_count() -> None:
    """Whatever fits the harness ceiling ships, however many messages it is."""
    conn = message_connection()
    message_ids = _send(conn, 8, body="short")

    with pytest.MonkeyPatch.context() as monkeypatch:
        rendered = _hook(conn, monkeypatch)

    assert all(message_id in rendered for message_id in message_ids)
    assert POINTER_BEGIN not in rendered
    assert set(_receipts(conn).values()) == {"injected"}


def test_a_lease_too_large_for_the_ceiling_settles_none_of_its_messages() -> None:
    """Overflow points at every leased message rather than shipping some."""
    conn = message_connection()
    message_ids = _send(conn, 10, body="short")

    with pytest.MonkeyPatch.context() as monkeypatch:
        rendered = _hook(conn, monkeypatch)

    assert POINTER_BEGIN in rendered
    for message_id in message_ids:
        assert f"yoke messages get {message_id} --json" in rendered
    assert set(_receipts(conn).values()) == {"pending"}
    assert "inline_overflow" in _attempt_results(conn)


def test_an_oversized_body_keeps_its_own_receipt_pending_and_named() -> None:
    conn = message_connection()
    (message_id,) = _send(conn, 1, body="x" * 12_000)

    with pytest.MonkeyPatch.context() as monkeypatch:
        rendered = _hook(conn, monkeypatch)

    assert POINTER_BEGIN in rendered
    assert message_id in rendered
    assert f"yoke messages get {message_id} --json" in rendered
    assert _receipts(conn) == {message_id: "pending"}
    assert "inline_overflow" in _attempt_results(conn)


def test_a_small_message_is_never_settled_by_an_oversized_sibling() -> None:
    conn = message_connection()
    (small_id,) = _send(conn, 1, body="decide the gate")
    (oversized_id,) = _send(conn, 1, body="x" * 12_000)

    with pytest.MonkeyPatch.context() as monkeypatch:
        overflowed = _hook(conn, monkeypatch)

        assert POINTER_BEGIN in overflowed
        assert _receipts(conn) == {small_id: "pending", oversized_id: "pending"}

        conn.execute(
            "UPDATE session_message_recipients SET state='acknowledged' "
            "WHERE message_id=?",
            (oversized_id,),
        )
        conn.commit()
        delivered = _hook(conn, monkeypatch, "PostToolUse")

    assert small_id in delivered
    assert POINTER_BEGIN not in delivered
    assert _receipts(conn)[small_id] == "injected"


def test_a_long_backlog_never_receipts_a_body_it_did_not_carry() -> None:
    """Over many hooks, every injected receipt has its body in some reply.

    A backlog too large for one composed block is pointed at on every hook
    rather than partially shipped, so the invariant to hold across a long
    session is not that the backlog drains inline — it is that no receipt
    ever runs ahead of the text that carried it.
    """
    conn = message_connection()
    message_ids = _send(conn, 18, body="y" * 200)
    acknowledged = set(message_ids[:12])
    remaining = set(message_ids) - acknowledged

    seen: list[str] = []
    with pytest.MonkeyPatch.context() as monkeypatch:
        for index in range(6):
            seen.append(_hook(conn, monkeypatch, EVENTS[index % 2]))
        expanded = "\n".join(seen)

        assert set(_receipts(conn).values()) == {"pending"}
        named = {
            message_id
            for message_id in message_ids
            if f"yoke messages get {message_id} --json" in expanded
        }
        assert len(named) == 10

        conn.execute(
            "UPDATE session_message_recipients SET state='acknowledged' "
            "WHERE message_id IN (%s)" % ",".join("?" for _ in acknowledged),
            tuple(acknowledged),
        )
        conn.commit()
        remainder = _hook(conn, monkeypatch)

    assert all(message_id in remainder for message_id in remaining)
    assert POINTER_BEGIN not in remainder
    injected = {
        message_id
        for message_id, state in _receipts(conn).items()
        if state == "injected"
    }
    assert injected == remaining
    assert (
        len(
            list_messages(
                conn,
                actor_id=10,
                caller_session_id=RECIPIENT,
                state="unacknowledged",
                limit=50,
            )
        )
        == 6
    )
