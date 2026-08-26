"""Bind a Cursor launch to its session, or say the proof is outstanding."""

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

    ACP ``session/new`` can return a UUID while the spawned agent has not yet
    run a hook-firing turn. Wait for the map, drive the documented prompt-mode
    resume once, and wait again — all inside a window shorter than the relay
    lease. A map that still misses is reported as a created native with its
    registration outstanding rather than as a failed create: see
    :func:`_registration_pending`.
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
        if uuid_session_id(conversation_id) is None:
            contain_launch_native(str(context.job_id), state_dir=state_dir)
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
        return _registration_pending(
            context,
            typed,
            conversation_id,
            attestation_handoff,
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


def _registration_pending(
    context: RelayExecutionContext,
    typed: object,
    conversation_id: str,
    attestation_handoff: LaunchAttestationHandoff | None,
) -> RelayAdapterResult:
    """Report a created native whose first hook has not landed yet.

    A Cursor cold start regularly outlives this adapter's map-proof window,
    and a native reaped at that moment is a healthy worker killed for being
    slow — measured: the relay gave up at 54s and the session registered ten
    seconds later, then ran unattested because its launch was already closed.
    The control plane already owns a registration deadline, and the machine
    already owns a supervision record that reaps a native which never
    registers, so the answer is to hand both the created native and say the
    proof is still outstanding, not to invent a third verdict here.

    The attestation is staged under the ACP conversation id, which is the id
    a Cursor session registers under, so a late first hook can still bind
    even where the environment channel is unavailable.
    """
    from yoke_harness.session_relay_cursor import CursorNativeResult, _result

    token = str(context.launch_attestation or "").strip()
    if token and attestation_handoff is not None:
        try:
            attestation_handoff(context.job_id, token, binding_id=conversation_id)
        except Exception:
            pass
    pending = CursorNativeResult(
        "native_created",
        conversation_id,
        getattr(typed, "exit_code", None),
        getattr(typed, "duration_ms", None),
        phase="registration_pending",
    )
    return _result(
        "native_created",
        native=pending,
        native_session_id=conversation_id,
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
