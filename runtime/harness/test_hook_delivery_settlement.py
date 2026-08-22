"""Aggregate hook-delivery output and durable settlement tests."""

from __future__ import annotations

from yoke_core.hooks import hook_delivery_settlement as settlement
from yoke_core.hooks import session_launch_attestation, session_message_delivery
from yoke_core.hooks.types import HookDecision, Outcome


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

    rendered, outcome = settlement.settle_model_deliveries(
        [message, launch], "orientation\n"
    )

    assert outcome == "allow"
    assert rendered == "orientation\nmessage-token\nlaunch-token\n"
    assert calls == [(rendered, False), (rendered, False)]


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

    rendered, outcome = settlement.settle_model_deliveries(
        [message, denial], "denied\n"
    )

    assert (rendered, outcome) == ("denied\n", "deny")
    assert calls == [("denied\n", True)]
