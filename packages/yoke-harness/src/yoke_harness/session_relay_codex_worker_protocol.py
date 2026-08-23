"""Bounded Codex owner-process request and outcome protocol."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Mapping

from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest


def request_payload(request: CodexNativeRequest) -> dict[str, object]:
    """Serialize non-secret request data for an anonymous stdin handoff."""
    return {
        "job_kind": request.job_kind,
        "job_id": request.job_id,
        "surface": request.surface,
        "surface_version": request.surface_version,
        "checkout": str(request.checkout),
        "requested_model": request.requested_model,
        "presentation": request.presentation,
        "target_liveness": request.target_liveness,
        "target_session_id": request.target_session_id,
        "wake_mode": request.wake_mode,
        "instruction_id": request.instruction_id,
        "native_instruction": request.native_instruction,
    }


def request_from_payload(payload: object) -> CodexNativeRequest:
    if not isinstance(payload, dict):
        raise ValueError("worker request must be an object")
    return CodexNativeRequest(
        job_kind=str(payload.get("job_kind") or ""),
        job_id=str(payload.get("job_id") or ""),
        surface=str(payload.get("surface") or ""),
        surface_version=str(payload.get("surface_version") or ""),
        checkout=Path(str(payload.get("checkout") or "")),
        requested_model=(
            str(payload["requested_model"]) if payload.get("requested_model") else None
        ),
        presentation=(
            str(payload["presentation"]) if payload.get("presentation") else None
        ),
        target_liveness=(
            str(payload["target_liveness"]) if payload.get("target_liveness") else None
        ),
        target_session_id=(
            str(payload["target_session_id"])
            if payload.get("target_session_id")
            else None
        ),
        wake_mode=(str(payload["wake_mode"]) if payload.get("wake_mode") else None),
        instruction_id=str(payload.get("instruction_id") or ""),
        native_instruction=str(payload.get("native_instruction") or ""),
    )


def rehydrate_launch_attestation(
    request: CodexNativeRequest,
    environ: Mapping[str, str],
) -> CodexNativeRequest | None:
    """Bind the env-only secret to the same launch id as the stdin metadata."""
    if request.job_kind != "launch":
        return request
    try:
        context = json.loads(environ.get(LAUNCH_CONTEXT_ENV, ""))
    except (TypeError, ValueError):
        return None
    if (
        not request.job_id
        or not isinstance(context, dict)
        or context.get("launch_id") != request.job_id
    ):
        return None
    attestation = context.get("attestation")
    if not isinstance(attestation, str) or not attestation.strip():
        return None
    return replace(request, launch_attestation=attestation.strip())


def outcome_payload(outcome: CodexNativeOutcome) -> dict[str, object]:
    return {
        "state": outcome.state,
        "native_session_id": outcome.native_session_id,
        "identity_correlated": outcome.identity_correlated,
        "exit_code": outcome.exit_code,
    }


def outcome_from_payload(payload: object) -> CodexNativeOutcome | None:
    if not isinstance(payload, dict):
        return None
    state = payload.get("state")
    if state not in {
        "accepted",
        "failed",
        "not_created",
        "not_found",
        "outcome_unknown",
        "unsupported_surface",
    }:
        return None
    native = payload.get("native_session_id")
    exit_code = payload.get("exit_code")
    return CodexNativeOutcome(
        state,
        str(native) if isinstance(native, str) and native else None,
        bool(payload.get("identity_correlated")),
        int(exit_code) if isinstance(exit_code, int) else None,
    )


def initial_failure(request: CodexNativeRequest) -> CodexNativeOutcome:
    return CodexNativeOutcome(
        "not_created" if request.job_kind == "launch" else "not_found"
    )


__all__ = [
    "initial_failure",
    "outcome_from_payload",
    "outcome_payload",
    "rehydrate_launch_attestation",
    "request_from_payload",
    "request_payload",
]
