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
from yoke_contracts.session_control.wake_delivery import (
    HOOK_DEFERRED_FOR_BUDGET_RESULT,
    INLINE_OVERFLOW_ATTEMPT_BOUND,
    INLINE_OVERFLOW_RESULT,
    inline_overflow_skip_reason,
)
from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    lease_for_hook,
)
from yoke_core.domain.session_message_queries import get_message, list_messages
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
        self,
        *,
        lease_id: str,
        injected: bool,
        result: str,
        message_results: dict[str, str] | None = None,
    ) -> None:
        complete_hook_lease(
            self.conn,
            lease_id=lease_id,
            injected=injected,
            result=result,
            message_results=message_results,
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


def test_a_lease_too_large_for_the_ceiling_ships_only_what_fits() -> None:
    conn = message_connection()
    message_ids = _send(conn, 10, body="y" * 400)

    with pytest.MonkeyPatch.context() as monkeypatch:
        rendered = _hook(conn, monkeypatch)

    receipts = _receipts(conn)
    injected = {mid for mid, state in receipts.items() if state == "injected"}
    pending = {mid for mid, state in receipts.items() if state == "pending"}
    assert injected and pending
    assert set(receipts) == set(message_ids)
    for message_id in injected:
        assert f"--- BEGIN YOKE SESSION MESSAGE {message_id} ---" in rendered
    for message_id in pending:
        assert f"--- BEGIN YOKE SESSION MESSAGE {message_id} ---" not in rendered
    assert INLINE_OVERFLOW_RESULT not in _attempt_results(conn)
    assert HOOK_DEFERRED_FOR_BUDGET_RESULT in _attempt_results(conn)


def test_an_oversized_body_keeps_its_own_receipt_pending_and_named() -> None:
    conn = message_connection()
    body = "x" * 12_000
    (message_id,) = _send(conn, 1, body=body)

    with pytest.MonkeyPatch.context() as monkeypatch:
        rendered = _hook(conn, monkeypatch)

    command = f"yoke messages get {message_id}"
    assert POINTER_BEGIN in rendered
    assert f"Read: {command}" in rendered
    assert f"{command} --json" not in rendered
    assert _receipts(conn) == {message_id: "pending"}
    assert INLINE_OVERFLOW_RESULT in _attempt_results(conn)
    details = get_message(
        conn, message_id=message_id, actor_id=10, session_id=RECIPIENT
    )
    assert details["body"] == f"message 0: {body}"
    assert details["attempts"][-1]["evidence"]["skip_reason"] == (
        inline_overflow_skip_reason(message_id)
    )


def test_a_small_message_is_never_blocked_by_an_oversized_sibling() -> None:
    conn = message_connection()
    (small_id,) = _send(conn, 1, body="decide the gate")
    (oversized_id,) = _send(conn, 1, body="x" * 12_000)

    with pytest.MonkeyPatch.context() as monkeypatch:
        rendered = _hook(conn, monkeypatch)

    assert f"--- BEGIN YOKE SESSION MESSAGE {small_id} ---" in rendered
    assert POINTER_BEGIN in rendered
    assert f"Read: yoke messages get {oversized_id}" in rendered
    assert _receipts(conn) == {small_id: "injected", oversized_id: "pending"}
    assert INLINE_OVERFLOW_RESULT in _attempt_results(conn)


def test_a_backlog_drains_across_hooks_and_never_receipts_a_missing_body() -> None:
    conn = message_connection()
    message_ids = _send(conn, 18, body="y" * 200)
    seen: list[str] = []
    with pytest.MonkeyPatch.context() as monkeypatch:
        for index in range(20):
            if set(_receipts(conn).values()) <= {"injected"}:
                break
            seen.append(_hook(conn, monkeypatch, EVENTS[index % 2]))
        else:
            raise AssertionError("backlog did not drain")
    expanded = "\n".join(seen)
    for message_id in message_ids:
        assert f"--- BEGIN YOKE SESSION MESSAGE {message_id} ---" in expanded
        assert _receipts(conn)[message_id] == "injected"
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
        == 18
    )


def test_overflow_retries_are_bounded_and_named() -> None:
    conn = message_connection()
    (message_id,) = _send(conn, 1, body="x" * 12_000)
    with pytest.MonkeyPatch.context() as monkeypatch:
        for index in range(INLINE_OVERFLOW_ATTEMPT_BOUND + 2):
            _hook(conn, monkeypatch, EVENTS[index % 2])
    overflowed = conn.execute(
        "SELECT COUNT(*) FROM session_message_attempts "
        "WHERE result_code=? AND completed_at IS NOT NULL",
        (INLINE_OVERFLOW_RESULT,),
    ).fetchone()
    assert int(overflowed[0]) == INLINE_OVERFLOW_ATTEMPT_BOUND
    assert _receipts(conn) == {message_id: "pending"}

