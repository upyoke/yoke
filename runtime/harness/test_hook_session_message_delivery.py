"""Focused hook delivery, settlement, reinjection, and wake-policy tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.hooks import session_message_delivery as delivery
from yoke_core.hooks.decision_render import render_codex_decision
from yoke_core.hooks.session_message_delivery_port import (
    LeasedSessionMessage,
    SessionMessageLease,
)
from yoke_core.hooks.types import HookContext, HookDecision, Outcome


NOW = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)


@dataclass
class FakePort:
    acknowledged: bool = False
    body: str = "Please re-run the focused verifier."
    leased: list[tuple[str, str, int]] = field(default_factory=list)
    completed: list[tuple[str, bool, str]] = field(default_factory=list)

    def lease_for_hook(
        self,
        *,
        session_id: str,
        hook_event: str,
        limit: int,
    ) -> SessionMessageLease | None:
        self.leased.append((session_id, hook_event, limit))
        if self.acknowledged:
            return None
        lease_id = f"lease-{len(self.leased)}"
        return SessionMessageLease(
            lease_id=lease_id,
            messages=(
                LeasedSessionMessage(
                    message_id="message-1",
                    body=self.body,
                    sender_actor_id=41,
                ),
            ),
        )

    def complete_hook_lease(
        self,
        *,
        lease_id: str,
        injected: bool,
        result: str,
    ) -> None:
        self.completed.append((lease_id, injected, result))


def _context(
    event_name: str = "PreToolUse",
    *,
    family: str = "codex",
    surface: str = "codex-desktop",
    session_id: str | None = "session-top",
    payload: dict | None = None,
) -> HookContext:
    return HookContext(
        event_name=event_name,
        executor_family=family,
        executor_surface=surface,
        payload=payload or {},
        session_id=session_id,
        now=NOW,
    )


def test_tool_event_returns_delimited_additional_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(_context())

    assert port.leased == [("session-top", "PreToolUse", 10)]
    rendered = decision.audit_fields["additionalContext"]
    assert "BEGIN YOKE SESSION MESSAGE message-1" in rendered
    assert "Authenticated sender actor: 41" in rendered
    assert "untrusted operational context" in rendered
    assert port.body in rendered
    assert "yoke messages acknowledge message-1" in rendered
    audit = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]
    assert audit["lease_id"] == "lease-1"
    assert audit["render_token"] == "YOKE_SESSION_MESSAGE_LEASE:lease-1"
    assert audit["output_field"] == "additionalContext"
    assert audit["rendered_text"] == rendered


def test_lifecycle_event_defers_stdout_until_aggregate_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(_context("SessionStart"))

    assert "stdout" not in decision.audit_fields
    assert "additionalContext" not in decision.audit_fields
    audit = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]
    assert audit["output_field"] == "stdout"
    assert "YOKE_SESSION_MESSAGE_LEASE:lease-1" in audit["rendered_text"]


def test_surface_event_gate_fails_open_without_leasing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(
        _context("PreToolUse", family="cursor", surface="cursor-desktop")
    )

    assert decision.outcome is Outcome.NOOP
    assert port.leased == []


def test_family_fallback_preserves_claude_model_visible_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(
        _context("PostToolUse", family="claude", surface="claude")
    )

    assert decision.outcome is Outcome.AUDIT_ONLY
    assert port.leased == [("session-top", "PostToolUse", 10)]


def test_missing_session_fails_open_without_leasing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(_context(session_id=None))

    assert decision.outcome is Outcome.NOOP
    assert port.leased == []


@pytest.mark.parametrize(
    "payload",
    [
        {"agent_type": "engineer"},
        {"subagent_execution": True},
        {"is_subagent_session": True, "subagent_session_id": "cursor-child"},
    ],
)
def test_child_hook_cannot_consume_or_hide_parent_message(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    child = delivery.evaluate(_context(payload=payload))
    parent = delivery.evaluate(_context())

    assert child.outcome is Outcome.NOOP
    assert port.leased == [("session-top", "PreToolUse", 10)]
    assert "message-1" in parent.audit_fields["additionalContext"]


def test_successful_render_marks_injected_only_after_output_contains_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    decision = delivery.evaluate(_context())
    stdout, code = render_codex_decision([decision], "PreToolUse")

    delivery.settle_after_render(
        [decision], rendered_text=stdout, denied=False, port=port
    )

    assert code == 0
    assert port.completed == [("lease-1", True, "injected")]


def test_sibling_denial_releases_lease_as_not_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    message = delivery.evaluate(_context())
    denial = HookDecision(
        outcome=Outcome.DENY,
        message="guard denied the tool call",
        block=True,
    )
    stdout, _ = render_codex_decision([message, denial], "PreToolUse")

    delivery.settle_after_render(
        [message, denial], rendered_text=stdout, denied=True, port=port
    )

    assert "YOKE_SESSION_MESSAGE_LEASE" not in stdout
    assert port.completed == [("lease-1", False, "dropped_by_sibling_denial")]


def test_missing_render_token_does_not_claim_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    decision = delivery.evaluate(_context())

    delivery.settle_after_render([decision], rendered_text="", denied=False, port=port)

    assert port.completed == [("lease-1", False, "render_output_missing")]


def test_message_reinjects_on_later_hook_until_explicit_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    first = delivery.evaluate(_context())
    second = delivery.evaluate(_context("PostToolUse"))
    port.acknowledged = True
    after_ack = delivery.evaluate(_context("PostToolUse"))

    assert "message-1" in first.audit_fields["additionalContext"]
    assert "message-1" in second.audit_fields["additionalContext"]
    assert after_ack.outcome is Outcome.NOOP
    assert len(port.leased) == 3


@pytest.mark.parametrize("state", ["acknowledged", "expired", "cancelled"])
def test_terminal_recipient_is_never_wake_eligible(state: str) -> None:
    assert not delivery.wake_eligible(
        recipient_state=state,
        liveness="ended",
        recipient_created_at=NOW,
        wake_after=NOW,
        last_hook_activity_at=None,
        idle_window=timedelta(minutes=10),
        now=NOW + timedelta(hours=1),
    )


def test_pending_without_post_message_hook_becomes_wake_eligible() -> None:
    assert delivery.wake_eligible(
        recipient_state="pending",
        liveness="active",
        recipient_created_at=NOW,
        wake_after=NOW + timedelta(minutes=10),
        last_hook_activity_at=NOW - timedelta(seconds=1),
        idle_window=timedelta(minutes=10),
        now=NOW + timedelta(minutes=10),
    )


def test_live_injected_unacknowledged_recipient_is_never_woken() -> None:
    assert not delivery.wake_eligible(
        recipient_state="injected",
        liveness="active",
        recipient_created_at=NOW,
        wake_after=NOW + timedelta(minutes=10),
        last_hook_activity_at=NOW + timedelta(minutes=2),
        idle_window=timedelta(minutes=10),
        now=NOW + timedelta(hours=2),
    )


def test_stale_injected_recipient_can_wake_after_new_idle_window() -> None:
    assert delivery.wake_eligible(
        recipient_state="injected",
        liveness="stale",
        recipient_created_at=NOW,
        wake_after=NOW + timedelta(minutes=10),
        last_hook_activity_at=NOW + timedelta(minutes=4),
        idle_window=timedelta(minutes=10),
        now=NOW + timedelta(minutes=14),
    )
