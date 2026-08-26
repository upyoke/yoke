"""Prove a Cursor launch registered, or reap the native that did not."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from yoke_harness.session_launch_containment import contain_launch_native
from yoke_harness.session_relay_cursor_identity import (
    ACP_SESSION_PARSE_EXPECTATION,
    CURSOR_REGISTRATION_TURN_WAIT_SECONDS,
    CURSOR_REGISTRATION_WAIT_SECONDS,
    ConversationLookup,
    LaunchAttestationHandoff,
    bind_launch_session,
    bounded_identity_snippet,
    uuid_session_id,
    wait_for_conversation_session,
)
from yoke_harness.session_relay_runtime import (
    RelayAdapterResult,
    RelayExecutionContext,
)


def complete_bound_launch(
    context: RelayExecutionContext,
    native: object,
    identity_lookup: ConversationLookup,
    attestation_handoff: LaunchAttestationHandoff | None,
    sleeper: Callable[[float], None],
    *,
    registration_turn: object | None = None,
    wait_seconds: float = CURSOR_REGISTRATION_WAIT_SECONDS,
    turn_wait_seconds: float = CURSOR_REGISTRATION_TURN_WAIT_SECONDS,
    state_dir: Path | None = None,
) -> RelayAdapterResult:
    """Bind only after the conversation map proves hooks fired.

    ACP ``session/new`` can return a UUID while the spawned agent never
    runs a hook-firing turn. Treat that as unregistered: drive the
    documented prompt-mode resume once, wait again, and reap if the map
    still misses — all inside a window shorter than the relay lease.
    """
    from yoke_harness.session_relay_cursor import (
        CursorNativeResult,
        _launch_result,
        _result,
    )

    typed = _as_native(native, CursorNativeResult)
    launched = _launch_result(typed)
    phase = typed.phase or (
        "native_running" if launched.result_code == "native_created" else "spawn"
    )
    conversation_id = launched.native_session_id
    if launched.result_code != "native_created" or not conversation_id:
        return _phased(launched, phase)
    resolution = wait_for_conversation_session(
        conversation_id,
        identity_lookup,
        wait_seconds=wait_seconds,
        sleeper=sleeper,
    )
    if resolution.session_id is None and registration_turn is not None:
        _drive_registration_turn(registration_turn, context, conversation_id)
        phase = "turn_start"
        resolution = wait_for_conversation_session(
            conversation_id,
            identity_lookup,
            wait_seconds=turn_wait_seconds,
            sleeper=sleeper,
        )
    if resolution.session_id is None:
        contain_launch_native(str(context.job_id), state_dir=state_dir)
        if uuid_session_id(conversation_id) is None:
            return _result(
                "not_created",
                native=CursorNativeResult(
                    "identity_parse_failed",
                    identity_output_snippet=bounded_identity_snippet(conversation_id),
                    identity_parse_expectation=ACP_SESSION_PARSE_EXPECTATION,
                    phase="spawn",
                ),
                evidence_code="identity_parse_failed",
            )
        failed = CursorNativeResult(
            "registration_unproven",
            conversation_id,
            typed.exit_code,
            typed.duration_ms,
            phase="registration",
        )
        return _result(
            "not_created",
            native=failed,
            native_session_id=conversation_id,
            evidence_code="registration_unproven",
        )
    binding = bind_launch_session(
        conversation_id,
        lambda _conversation_id: resolution.session_id,
        attestation_handoff,
        context.job_id,
        str(context.launch_attestation or ""),
        sleeper=sleeper,
    )
    combined = CursorNativeResult(
        binding.result_code,
        binding.session_id,
        typed.exit_code,
        max(0, int(typed.duration_ms or 0) + binding.duration_ms),
        identity_output_snippet=binding.output_snippet,
        identity_parse_expectation=binding.parse_expectation,
        phase="native_running" if binding.result_code == "native_created" else phase,
    )
    if binding.result_code != "native_created":
        contain_launch_native(str(context.job_id), state_dir=state_dir)
        report = (
            "not_created"
            if binding.result_code == "identity_parse_failed"
            else "outcome_unknown"
        )
        return _result(
            report,
            native=combined,
            native_session_id=binding.session_id,
            evidence_code=binding.result_code,
        )
    return _result(
        "native_created",
        native=combined,
        native_session_id=binding.session_id,
    )


def _as_native(native: object, cls: type) -> object:
    if isinstance(native, cls):
        return native
    return cls(
        str(getattr(native, "result_code", "outcome_unknown")),
        getattr(native, "native_session_id", None),
        getattr(native, "exit_code", None),
        getattr(native, "duration_ms", None),
        identity_output_snippet=getattr(native, "identity_output_snippet", None),
        identity_parse_expectation=getattr(native, "identity_parse_expectation", None),
        phase=getattr(native, "phase", None),
    )


def _phased(launched: RelayAdapterResult, phase: str) -> RelayAdapterResult:
    evidence = dict(launched.evidence)
    evidence.setdefault("native_launch_phase", phase)
    return RelayAdapterResult(
        launched.result_code,
        native_session_id=launched.native_session_id,
        adapter_revision=launched.adapter_revision,
        evidence=evidence,
        private_diagnostic=launched.private_diagnostic,
    )


def _drive_registration_turn(
    port: object,
    context: RelayExecutionContext,
    session_id: str,
) -> None:
    from yoke_harness.session_relay_cursor import CursorWakeRequest

    resume = getattr(port, "resume_chat", None)
    if not callable(resume):
        return
    try:
        resume(
            CursorWakeRequest(
                checkout=context.checkout,
                target_session_id=session_id,
                surface_version=str(context.surface_version),
                target_liveness="ended",
                wake_mode="waiting",
                native_instruction=context.native_instruction,
            )
        )
    except Exception:
        return


__all__ = ["complete_bound_launch"]
