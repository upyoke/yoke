"""What a declining hook evaluation records, and what a resume still gets.

The two halves belong together: a resumed Cursor session takes delivery on
exactly the path a fresh one does, and when some path does decline it says
which one rather than leaving an operator to infer a mechanism from an
``injection_count`` that never moved.
"""

from __future__ import annotations

import logging

import pytest

from yoke_core.domain import session_message_delivery_probe as probe
from yoke_core.domain.session_message_delivery_probe import (
    DELIVERY_PROBE_ADAPTER_REVISION,
    PROBE_LEASE_FAILED,
    PROBE_NO_LEASABLE_RECEIPT,
    PROBE_SESSION_NOT_DELIVERABLE,
    PROBE_SUBAGENT_EXIT,
    record_undelivered_receipts,
)
from yoke_core.domain.session_message_service import send_message
from yoke_core.hooks import session_message_delivery as delivery
from yoke_core.hooks.types import Outcome
from runtime.harness.session_message_delivery_test_helpers import (
    MESSAGE_ID,
    FakePort,
    hook_context,
)
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


CURSOR_START = {"family": "cursor", "surface": "cursor-cli"}


def _port(monkeypatch: pytest.MonkeyPatch, **kwargs) -> FakePort:
    port = FakePort(**kwargs)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    return port


def test_a_resumed_cursor_start_takes_delivery_on_the_fresh_start_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resume has no delivery path of its own — there is only one.

    The evaluator is told the event and the session, never whether the
    session is opening for the first time or reopening, so a woken turn
    reaches the same lease a first turn does.
    """
    port = _port(monkeypatch)

    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))

    assert port.leased == [("session-top", "SessionStart", 10)]
    assert port.probed == []
    rendered = decision.audit_fields["additionalContext"]
    assert (
        f"BEGIN YOKE SESSION MESSAGE DELIVERY YOKE_SESSION_MESSAGE_LEASE:lease-1 {MESSAGE_ID}"
        in rendered
    )
    assert "Authenticated sender: actor 41" in rendered
    assert '| "Please re-run the focused verifier."' in rendered
    assert "=== END YOKE SESSION MESSAGE DELIVERY ===" in rendered
    assert f"yoke messages acknowledge {MESSAGE_ID}" in rendered


def test_a_resumed_cursor_start_settles_injected_once_its_reply_carries_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(monkeypatch)
    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))
    token = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]["render_token"]

    delivery.settle_after_render(
        [decision],
        rendered_text='{"additional_context": "' + token + '"}',
        denied=False,
        port=port,
    )

    assert port.completed == [("lease-1", True, "injected")]


def test_an_undeliverable_session_records_that_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(monkeypatch, acknowledged=True)

    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))

    assert decision.outcome is Outcome.NOOP
    assert port.probed == [
        ("session-top", "SessionStart", PROBE_SESSION_NOT_DELIVERABLE, "")
    ]


def test_a_failing_lease_records_its_class_and_never_its_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(
        monkeypatch,
        lease_error=TimeoutError("canceling statement due to lock timeout"),
    )

    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))

    assert decision.outcome is Outcome.NOOP
    assert port.probed == [
        ("session-top", "SessionStart", PROBE_LEASE_FAILED, "TimeoutError")
    ]


def test_a_lease_that_carried_nothing_is_released_and_then_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(monkeypatch, empty_lease=True)

    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))

    assert decision.outcome is Outcome.NOOP
    assert port.completed == [("lease-1", False, "empty_lease")]
    assert port.probed == [
        ("session-top", "SessionStart", PROBE_NO_LEASABLE_RECEIPT, "")
    ]


def test_a_failing_probe_never_turns_a_quiet_miss_into_a_failing_hook(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    port = _port(monkeypatch, acknowledged=True)

    def refuse(**_kwargs: object) -> int:
        raise RuntimeError("control plane unreachable")

    monkeypatch.setattr(port, "probe_undelivered", refuse)

    with caplog.at_level(logging.WARNING, logger=delivery.__name__):
        decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))

    assert decision.outcome is Outcome.NOOP
    assert "delivery probe write failed: RuntimeError" in caplog.text
    assert "control plane unreachable" not in caplog.text


def test_a_session_this_process_cannot_name_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(monkeypatch)

    decision = delivery.evaluate(hook_context("SessionStart", session_id=None))

    assert decision.outcome is Outcome.NOOP
    assert port.leased == []
    assert port.probed == []


def test_an_event_the_surface_cannot_inject_on_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a fact of the moment — the capability table already answers it."""
    port = _port(monkeypatch)

    decision = delivery.evaluate(
        hook_context("PreToolUse", family="cursor", surface="cursor-cli")
    )

    assert decision.outcome is Outcome.NOOP
    assert port.leased == []
    assert port.probed == []


class _DatabaseProbePort(FakePort):
    """Writes probes through the real recorder into an in-memory inbox."""

    def __init__(self, conn) -> None:
        super().__init__()
        self.conn = conn

    def probe_undelivered(self, **kwargs: str) -> int:
        return record_undelivered_receipts(self.conn, **kwargs)


def _subagent_probe_rows(
    monkeypatch: pytest.MonkeyPatch, *, pending: bool
) -> list[tuple[str, str]]:
    monkeypatch.setattr(probe, "utc_now", lambda: NOW)
    conn = message_connection()
    if pending:
        send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(session_ids=["s1"]),
            body="Persistent instructions.",
            now=NOW,
        )
    port = _DatabaseProbePort(conn)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(
        hook_context(session_id="s1", payload={"agent_type": "explorer"})
    )

    assert decision.outcome is Outcome.NOOP
    assert port.leased == []
    return [
        (row["result_code"], row["state"])
        for row in conn.execute(
            "SELECT a.result_code, r.state FROM session_message_attempts a "
            "JOIN session_message_recipients r ON r.message_id=a.message_id "
            "AND r.session_id=a.target_session_id WHERE a.adapter_revision=?",
            (DELIVERY_PROBE_ADAPTER_REVISION,),
        ).fetchall()
    ]


def test_a_subagent_event_records_why_the_pending_envelope_stayed_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subagent's tool calls reach the server while the parent's envelope
    waits; the record names that exit instead of leaving a silent gap."""
    rows = _subagent_probe_rows(monkeypatch, pending=True)

    assert rows == [(PROBE_SUBAGENT_EXIT, "pending")]


def test_a_subagent_event_with_nothing_pending_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _subagent_probe_rows(monkeypatch, pending=False) == []
