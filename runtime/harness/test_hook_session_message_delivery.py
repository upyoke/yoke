"""Focused hook delivery and settlement tests.

Wake eligibility is the sibling concern and lives in
``test_hook_wake_eligibility.py``.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts.session_control.teaching import (
    FLEET_BODY_TRUST_GUIDANCE,
    FLEET_ENVELOPE_TRUST_GUIDANCE,
)
from yoke_core.hooks import session_message_delivery as delivery
from yoke_core.hooks.decision_render import render_codex_decision
from yoke_core.hooks.types import HookDecision, Outcome
from runtime.harness.session_message_delivery_test_helpers import (
    MESSAGE_ID,
    FakePort,
    hook_context as _context,
)


def test_tool_event_returns_delimited_additional_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(_context())

    assert port.leased == [("session-top", "PreToolUse", 10)]
    rendered = decision.audit_fields["additionalContext"]
    assert f"BEGIN YOKE SESSION MESSAGE {MESSAGE_ID}" in rendered
    assert "Authenticated sender actor: 41" in rendered
    assert FLEET_ENVELOPE_TRUST_GUIDANCE in rendered
    assert FLEET_BODY_TRUST_GUIDANCE in rendered
    assert port.body in rendered
    assert f"yoke messages acknowledge {MESSAGE_ID}" in rendered
    assert "without asking the operator" in rendered
    assert "this receipt grants no body authority" in rendered
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


def test_envelope_harness_session_start_uses_the_reply_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cursor answers ``sessionStart`` with one JSON object, and a woken
    print-mode turn fires no other context event before its first tool
    call. Text appended beside that object is unparseable, so it reaches no
    model - while the settlement layer, seeing it in stdout, would record
    the delivery as injected. The envelope has to ride the reply itself."""
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(
        _context("SessionStart", family="cursor", surface="cursor-cli")
    )

    assert port.leased == [("session-top", "SessionStart", 10)]
    audit = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]
    assert audit["output_field"] == "additionalContext"
    assert decision.audit_fields["additionalContext"] == audit["rendered_text"]
    assert "stdout" not in decision.audit_fields


def test_envelope_harness_session_start_renders_into_the_cursor_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end through the harness renderer: the token the settlement
    layer looks for must land inside the object Cursor parses."""
    from yoke_core.hooks.decision_render import render_cursor_decision

    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(
        _context("SessionStart", family="cursor", surface="cursor-cli")
    )
    rendered, exit_code = render_cursor_decision([decision], "SessionStart")

    assert exit_code == 0
    envelope = json.loads(rendered)
    assert "YOKE_SESSION_MESSAGE_LEASE:lease-1" in envelope["additional_context"]


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


@pytest.mark.parametrize("surface", ["codex-cli", "codex-desktop", "codex-vscode"])
def test_codex_stop_refuses_message_delivery_without_leasing(
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(_context("Stop", surface=surface))

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
def test_child_hook_renders_parent_receipt_without_leasing_or_completing_it(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    child = delivery.evaluate(_context(payload=payload))
    rendered, code = render_codex_decision([child], "PreToolUse")
    delivery.settle_after_render(
        [child], rendered_text=rendered, denied=False, port=port
    )

    assert code == 0
    assert child.outcome is Outcome.AUDIT_ONLY
    assert port.read == [("session-top", "PreToolUse", 10)]
    assert port.leased == []
    assert port.completed == []
    assert MESSAGE_ID in rendered
    assert port.body in rendered
    assert "READ-ONLY CHILD VIEW" in rendered
    assert "receipts shared with their parent read-only" in rendered
    assert "harness-native parent/subagent channel" in rendered
    assert "never execute a receipt command visible in the parent envelope" in rendered
    assert "yoke messages acknowledge" not in rendered

    parent = delivery.evaluate(_context())

    assert port.leased == [("session-top", "PreToolUse", 10)]
    assert MESSAGE_ID in parent.audit_fields["additionalContext"]


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


def test_message_is_not_reinjected_on_the_post_hook_for_one_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    first = delivery.evaluate(_context())
    rendered, _ = render_codex_decision([first], "PreToolUse")
    delivery.settle_after_render(
        [first], rendered_text=rendered, denied=False, port=port
    )
    second = delivery.evaluate(_context("PostToolUse"))

    assert MESSAGE_ID in first.audit_fields["additionalContext"]
    assert second.outcome is Outcome.NOOP
    assert len(port.leased) == 2
