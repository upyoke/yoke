"""Hook contracts for launch attestation and first-instruction delivery."""

from __future__ import annotations

from yoke_contracts.session_control.launch_bootstrap import (
    AUTOMATIC_LAUNCH_REGISTRATION_TEACHING,
)
from yoke_core.domain.session_launch_types import LaunchRegistrationInjection
from yoke_core.hooks import session_launch_attestation as launch_hook
from yoke_core.hooks.types import HookContext, Outcome


class _Connection:
    def close(self) -> None:
        pass


def _record(
    event_name: str = "PreToolUse", executor_family: str = "codex"
) -> HookContext:
    return HookContext(
        event_name=event_name,
        executor_family=executor_family,
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


def test_claude_session_start_defers_stdout_until_aggregate_settlement(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        launch_hook,
        "prepare_launch_registration",
        lambda conn, **kwargs: _injection(),
    )
    decision = launch_hook.evaluate_launch_attestation(
        _record("SessionStart", "claude"),
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
    assert AUTOMATIC_LAUNCH_REGISTRATION_TEACHING in rendered
    assert "yoke messages acknowledge message-1" in rendered


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


def test_superseded_launch_code_yields_a_stop_context() -> None:
    for state in ("succeeded", "failed", "expired"):
        context = launch_hook._superseded_launch_stop_context(
            "invalid_state", launch_state=state
        )
        assert context is not None and "Stop now" in context
    for code in ("attestation_consumed", "late_registration"):
        context = launch_hook._superseded_launch_stop_context(code)
        assert context is not None and "Stop now" in context
    for state in ("launching", "awaiting_registration"):
        assert (
            launch_hook._superseded_launch_stop_context(
                "invalid_state", launch_state=state
            )
            is None
        )
    assert launch_hook._superseded_launch_stop_context("attestation_invalid") is None


def test_launching_registration_retries_without_recording_or_stopping(
    monkeypatch,
) -> None:
    from yoke_core.domain.session_launch_types import SessionLaunchError

    attempts = 0
    refusals = []

    def prepare(conn, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise SessionLaunchError(
                "invalid_state",
                "native identity report has not landed",
                launch_state="launching",
            )
        return _injection()

    monkeypatch.setattr(launch_hook, "prepare_launch_registration", prepare)
    monkeypatch.setattr(
        launch_hook,
        "record_registration_refusal",
        lambda *args, **kwargs: refusals.append((args, kwargs)),
    )

    early = launch_hook.evaluate_launch_attestation(
        _record("SessionStart"), connect=_Connection
    )
    delivered = launch_hook.evaluate_launch_attestation(_record(), connect=_Connection)

    assert early.outcome == Outcome.WARN
    assert early.audit_fields == {"session_launch_error": "invalid_state"}
    assert delivered.outcome == Outcome.AUDIT_ONLY
    assert "Inspect the assigned work." in delivered.audit_fields["additionalContext"]
    assert refusals == []


def test_superseded_launch_warns_the_opening_native_to_stop(monkeypatch) -> None:
    from yoke_core.domain.session_launch_types import SessionLaunchError

    def _raise(conn, **kwargs):
        raise SessionLaunchError("attestation_consumed", "attestation is single-use")

    monkeypatch.setattr(launch_hook, "_prepare_or_record_refusal", _raise)
    decision = launch_hook.evaluate_launch_attestation(
        _record("SessionStart"), connect=lambda: _Connection()
    )

    assert decision.outcome == Outcome.WARN
    assert decision.audit_fields["session_launch_error"] == "attestation_consumed"
    stop = decision.audit_fields["additionalContext"]
    assert "superseded" in stop.lower()
    assert "Stop now" in stop


def test_superseded_launch_warns_without_stop_context_at_turn_end(monkeypatch) -> None:
    from yoke_core.domain.session_launch_types import SessionLaunchError

    def _raise(conn, **kwargs):
        raise SessionLaunchError("attestation_consumed", "attestation is single-use")

    monkeypatch.setattr(launch_hook, "_prepare_or_record_refusal", _raise)

    for event_name in ("Stop", "SessionEnd"):
        decision = launch_hook.evaluate_launch_attestation(
            _record(event_name), connect=lambda: _Connection()
        )

        assert decision.outcome == Outcome.WARN
        assert decision.audit_fields == {"session_launch_error": "attestation_consumed"}
