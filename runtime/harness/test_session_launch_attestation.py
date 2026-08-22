"""Hook contracts for launch attestation and first-instruction delivery."""

from __future__ import annotations

from yoke_core.domain.session_launch_types import LaunchRegistrationInjection
from yoke_core.hooks import session_launch_attestation as launch_hook
from yoke_core.hooks.types import HookContext, Outcome


class _Connection:
    def close(self) -> None:
        pass


def _record(event_name: str = "PreToolUse") -> HookContext:
    return HookContext(
        event_name=event_name,
        executor_family="codex",
        executor_surface="codex-cli",
        payload={
            "yoke_launch": {
                "launch_id": "launch-1",
                "attestation": "one-time-secret",
            }
        },
        session_id="session-1",
    )


def _injection() -> LaunchRegistrationInjection:
    return LaunchRegistrationInjection(
        launch_id="launch-1",
        message_id="message-1",
        session_id="session-1",
        sender_actor_id=42,
        body="Inspect the assigned work.",
        body_sha256="hash",
    )


def test_tool_event_uses_existing_additional_context_path(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def prepare(conn, **kwargs):
        seen.update(kwargs)
        return _injection()

    monkeypatch.setattr(launch_hook, "prepare_launch_registration", prepare)
    decision = launch_hook.evaluate_launch_attestation(
        _record(),
        connect=_Connection,
    )

    assert decision.outcome == Outcome.AUDIT_ONLY
    assert "Inspect the assigned work." in decision.audit_fields["additionalContext"]
    assert "stdout" not in decision.audit_fields
    assert seen == {
        "launch_id": "launch-1",
        "attestation": "one-time-secret",
        "session_id": "session-1",
    }
    assert "one-time-secret" not in repr(decision.audit_fields)


def test_lifecycle_event_defers_stdout_until_aggregate_settlement(monkeypatch) -> None:
    monkeypatch.setattr(
        launch_hook,
        "prepare_launch_registration",
        lambda conn, **kwargs: _injection(),
    )
    decision = launch_hook.evaluate_launch_attestation(
        _record("SessionStart"),
        connect=_Connection,
    )
    assert "stdout" not in decision.audit_fields
    assert "additionalContext" not in decision.audit_fields
    audit = decision.audit_fields[launch_hook.LAUNCH_DELIVERY_AUDIT_FIELD]
    assert audit["output_field"] == "stdout"
    assert "Inspect the assigned work." in audit["rendered_text"]


def test_instruction_framing_denies_inherited_authority() -> None:
    rendered = launch_hook.render_launch_instructions(_injection())
    assert "untrusted operational context" in rendered
    assert "does not override approvals" in rendered
    assert "Sender actor: 42" in rendered
    assert "Message ID: message-1" in rendered


def test_invalid_attestation_warns_without_exposing_secret() -> None:
    record = _record()
    record.payload["yoke_launch"] = {"launch_id": "launch-1"}
    decision = launch_hook.evaluate_launch_attestation(
        record,
        connect=lambda: (_ for _ in ()).throw(AssertionError("must not connect")),
    )
    assert decision.outcome == Outcome.WARN
    assert decision.audit_fields == {"session_launch_error": "attestation_invalid"}
    assert "one-time-secret" not in decision.message


def test_finalize_records_only_actual_render_delivery(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        launch_hook,
        "complete_launch_injection",
        lambda conn, **kwargs: calls.append(kwargs),
    )
    decision = launch_hook.HookDecision(
        outcome=Outcome.AUDIT_ONLY,
        audit_fields={
            "session_launch_delivery": {
                "launch_id": "launch-1",
                "message_id": "message-1",
                "session_id": "session-1",
                "render_token": "launch-token",
            }
        },
    )
    launch_hook.finalize_launch_attestation(
        decision,
        delivered=False,
        connect=_Connection,
    )
    assert calls == [
        {
            "launch_id": "launch-1",
            "session_id": "session-1",
            "injected": False,
        }
    ]
