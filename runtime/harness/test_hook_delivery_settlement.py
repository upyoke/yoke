"""Aggregate hook-delivery output and durable settlement tests."""

from __future__ import annotations

import json

from yoke_core.hooks import hook_delivery_settlement as settlement
from yoke_core.hooks import (
    session_broker_wake,
    session_launch_attestation,
    session_message_delivery,
)
from yoke_core.hooks.decision_render import render_codex_decision
from yoke_core.hooks.types import HookDecision, Outcome
from runtime.harness.session_message_delivery_test_helpers import (
    REPORT_CLAIMED_AT,
    REPORT_FINGERPRINT,
    REPORT_NOT_AFTER,
    FakePort,
    hook_context,
)


_REPORT = "=== BEGIN YOKE FLEET REPORT ===\ndigest\n=== END YOKE FLEET REPORT ==="


def _delivery(field: str, token: str, body: str) -> HookDecision:
    return HookDecision(
        outcome=Outcome.AUDIT_ONLY,
        audit_fields={
            field: {
                "lease_id": "lease-1",
                "launch_id": "launch-1",
                "session_id": "session-1",
                "render_token": token,
                "output_field": "stdout",
                "rendered_text": body,
            }
        },
    )


def test_allowed_lifecycle_delivery_is_appended_then_settled(monkeypatch) -> None:
    message = _delivery(
        session_message_delivery.DELIVERY_AUDIT_FIELD,
        "message-token",
        "message-token\n",
    )
    launch = _delivery(
        session_launch_attestation.LAUNCH_DELIVERY_AUDIT_FIELD,
        "launch-token",
        "launch-token\n",
    )
    broker = _delivery(
        session_broker_wake.BROKER_AUDIT_FIELD,
        "broker-token",
        "broker-token\n",
    )
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        session_message_delivery,
        "settle_after_render",
        lambda decisions, *, rendered_text, denied: calls.append(
            (rendered_text, denied)
        ),
    )
    monkeypatch.setattr(
        session_launch_attestation,
        "settle_after_render",
        lambda decisions, *, rendered_text, denied: calls.append(
            (rendered_text, denied)
        ),
    )
    monkeypatch.setattr(
        session_broker_wake,
        "settle_after_render",
        lambda decisions, *, rendered_text, denied: calls.append(
            (rendered_text, denied)
        ),
    )

    rendered, outcome = settlement.settle_model_deliveries(
        [message, launch, broker], "orientation\n"
    )

    assert outcome == "allow"
    assert rendered == "orientation\nmessage-token\nlaunch-token\nbroker-token\n"
    assert calls == [(rendered, False), (rendered, False), (rendered, False)]


def test_sibling_denial_suppresses_provisional_stdout(monkeypatch) -> None:
    message = _delivery(
        session_message_delivery.DELIVERY_AUDIT_FIELD,
        "message-token",
        "message-token\n",
    )
    denial = HookDecision(outcome=Outcome.DENY, block=True)
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        session_message_delivery,
        "settle_after_render",
        lambda decisions, *, rendered_text, denied: calls.append(
            (rendered_text, denied)
        ),
    )
    monkeypatch.setattr(
        session_launch_attestation,
        "settle_after_render",
        lambda decisions, *, rendered_text, denied: None,
    )
    monkeypatch.setattr(
        session_broker_wake,
        "settle_after_render",
        lambda decisions, *, rendered_text, denied: None,
    )

    rendered, outcome = settlement.settle_model_deliveries(
        [message, denial], "denied\n"
    )

    assert (rendered, outcome) == ("denied\n", "deny")
    assert calls == [("denied\n", True)]


# ---------------------------------------------------------------------------
# The evidenced defect: message (raw-stdout channel) + report used to
# concatenate a JSON envelope with a raw message body -- valid JSON followed
# by unrelated bytes -- while settlement still recorded the message as
# injected. Fixed: both ride one coherent reply, and settlement only
# confirms delivery once that reply is actually well-formed.
# ---------------------------------------------------------------------------


def test_message_and_report_settle_correctly_on_an_opening_event(monkeypatch) -> None:
    port = FakePort(report=_REPORT)
    monkeypatch.setattr(session_message_delivery, "_delivery_port", lambda: port)

    decision = session_message_delivery.evaluate(hook_context("SessionStart"))
    rendered_text, exit_code = render_codex_decision([decision], "SessionStart")

    # Nothing here targets the additionalContext channel -- the report rode
    # the message's own stdout body, so the decision renderer has nothing
    # to JSON-wrap.
    assert (rendered_text, exit_code) == ("", 0)

    final_text, outcome = settlement.settle_model_deliveries([decision], rendered_text)

    assert outcome == "allow"
    assert final_text.lstrip()[:1] not in ("{", "[")
    assert final_text.index("SESSION MESSAGE DELIVERY") < final_text.index(
        "FLEET REPORT"
    )
    assert port.completed == [("lease-1", True, "injected")]
    assert port.confirmed_reports == [
        ("session-top", REPORT_FINGERPRINT, REPORT_CLAIMED_AT, REPORT_NOT_AFTER)
    ]


def test_message_and_report_settle_correctly_on_a_tool_event(monkeypatch) -> None:
    """The additionalContext channel (a non-opening event) is unaffected:
    message and report already composed into one JSON envelope, and
    settlement still confirms both once the whole chain is known-good."""
    port = FakePort(report=_REPORT)
    monkeypatch.setattr(session_message_delivery, "_delivery_port", lambda: port)

    decision = session_message_delivery.evaluate(hook_context("PreToolUse"))
    rendered_text, exit_code = render_codex_decision([decision], "PreToolUse")

    assert exit_code == 0
    body = json.loads(rendered_text)["hookSpecificOutput"]["additionalContext"]
    assert body.index("SESSION MESSAGE DELIVERY") < body.index("FLEET REPORT")

    final_text, outcome = settlement.settle_model_deliveries([decision], rendered_text)

    assert outcome == "allow"
    assert port.completed == [("lease-1", True, "injected")]
    assert port.confirmed_reports == [
        ("session-top", REPORT_FINGERPRINT, REPORT_CLAIMED_AT, REPORT_NOT_AFTER)
    ]


def test_denied_sibling_leaves_the_report_unconfirmed(monkeypatch) -> None:
    port = FakePort(report=_REPORT)
    monkeypatch.setattr(session_message_delivery, "_delivery_port", lambda: port)
    message = session_message_delivery.evaluate(hook_context("SessionStart"))
    denial = HookDecision(outcome=Outcome.DENY, block=True)
    rendered_text, _exit_code = render_codex_decision([message, denial], "SessionStart")

    final_text, outcome = settlement.settle_model_deliveries(
        [message, denial], rendered_text
    )

    assert outcome == "deny"
    assert "FLEET REPORT" not in final_text
    assert port.completed == [("lease-1", False, "dropped_by_sibling_denial")]
    assert port.confirmed_reports == []


def test_malformed_reply_does_not_settle_the_message_as_delivered(monkeypatch) -> None:
    """A JSON value followed by unrelated raw bytes ('Extra data') must not
    settle as delivered even though the token is a literal substring -- the
    exact shape a broken composer used to hand settlement."""
    port = FakePort()
    monkeypatch.setattr(session_message_delivery, "_delivery_port", lambda: port)
    decision = session_message_delivery.evaluate(hook_context("PreToolUse"))
    token = decision.audit_fields[session_message_delivery.DELIVERY_AUDIT_FIELD][
        "render_token"
    ]
    malformed = (
        json.dumps({"hookSpecificOutput": {"additionalContext": "unrelated"}})
        + f"\n=== BEGIN YOKE SESSION MESSAGE DELIVERY {token} ===\nbody"
    )

    session_message_delivery.settle_after_render(
        [decision], rendered_text=malformed, denied=False, port=port
    )

    assert port.completed == [("lease-1", False, "render_output_missing")]


def test_malformed_reply_does_not_confirm_the_report(monkeypatch) -> None:
    port = FakePort(empty_lease=True, report=_REPORT)
    monkeypatch.setattr(session_message_delivery, "_delivery_port", lambda: port)
    decision = session_message_delivery.evaluate(hook_context("PreToolUse"))
    malformed = json.dumps({"a": 1}) + "trailing"

    session_message_delivery.settle_after_render(
        [decision], rendered_text=malformed, denied=False, port=port
    )

    assert port.confirmed_reports == []
