"""Closed in-process adapter registry for one relay-leased native job."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, cast

from yoke_cli.config import machine_config
from yoke_contracts.session_control.private_route_qualification import (
    PrivateRouteQualificationGrant,
)


WakeMode = Literal["waiting", "idle_timeout"]
WAITING_WAKE_MODE: WakeMode = "waiting"
IDLE_TIMEOUT_WAKE_MODE: WakeMode = "idle_timeout"
_WAKE_MODES = frozenset({WAITING_WAKE_MODE, IDLE_TIMEOUT_WAKE_MODE})
_LIVENESS_OPERATION = {
    "active": "message_active",
    "stale": "message_idle",
    "ended": "message_stopped",
}


def normalize_wake_mode(value: object) -> WakeMode | None:
    if not isinstance(value, str) or value not in _WAKE_MODES:
        return None
    return cast(WakeMode, value)


def wake_operation(value: object, target_liveness: object) -> str | None:
    mode = normalize_wake_mode(value)
    if mode == WAITING_WAKE_MODE:
        return "message_stopped"
    if mode == IDLE_TIMEOUT_WAKE_MODE:
        return _LIVENESS_OPERATION.get(str(target_liveness or ""))
    return None


@dataclass(frozen=True)
class RelayExecutionContext:
    job_kind: str
    job_id: str
    lease_id: str
    surface: str
    project_id: int
    checkout: Path
    native_instruction: str
    surface_version: str | None = None
    message_id: str | None = None
    target_session_id: str | None = None
    target_native_thread_id: str | None = None
    requested_model: str | None = None
    presentation: str | None = None
    session_name: str | None = None
    launch_deadline_at: str | None = None
    target_liveness: str | None = None
    wake_mode: WakeMode | None = None
    wake_route: str | None = None
    launch_attestation: str | None = field(default=None, repr=False)
    launch_progress_reporter: Callable[[Mapping[str, object]], bool] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    launch_registration_resolver: (
        Callable[[str], Mapping[str, object] | None] | None
    ) = field(default=None, repr=False, compare=False)
    private_route_qualification: PrivateRouteQualificationGrant | None = field(
        default=None,
        repr=False,
    )


def native_instruction_targets_job(context: RelayExecutionContext) -> bool:
    """True when the control plane's sentence names this job's own target.

    The instruction has exactly one author, the control plane, and the
    adapter hands the native those bytes rather than a copy it re-derived.
    An adapter that rebuilt the sentence and demanded equality tied the two
    builds into lockstep: the wording changed on the relay before the
    control plane it talks to had it, every wake on the machine refused as
    ``instruction_invalid``, and four steering waits died over two hours
    against a relay that never spawned anything. Nothing about a wording
    edit should be able to do that, so the wording is no longer the test.

    What the adapter must still refuse is a sentence aimed somewhere else —
    a wake carrying another message's identity, a launch carrying another
    launch's. That is what the identity below checks, and it is the only
    part of the instruction an adapter can verify without owning its text.
    """
    instruction = context.native_instruction
    if not isinstance(instruction, str) or not instruction.strip():
        return False
    if context.job_kind == "launch":
        target = str(context.job_id or "")
    elif context.job_kind == "wake":
        target = str(context.message_id or "")
    else:
        return False
    return bool(target) and target in instruction


@dataclass(frozen=True)
class RelayAdapterResult:
    result_code: str
    native_session_id: str | None = None
    adapter_revision: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    #: An evidence read's listing and file tail. Every other job reports only
    #: through the bounded ``evidence`` allowlist, which holds short named
    #: facts and would drop a file's contents without saying so.
    document: Mapping[str, Any] | None = None
    private_diagnostic: "RelayPrivateDiagnostic | None" = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True)
class RelayPrivateDiagnostic:
    """Native failure streams that must never cross the relay report wire."""

    failure_class: str
    error_step: str = "native_command"
    stdout: bytes = field(default=b"", repr=False)
    stderr: bytes = field(default=b"", repr=False)


RelayAdapter = Callable[[RelayExecutionContext], RelayAdapterResult]
_ADAPTERS: dict[str, RelayAdapter] = {}


def register_relay_adapter(surface: str, adapter: RelayAdapter) -> None:
    if surface in _ADAPTERS:
        raise RuntimeError(f"relay adapter already registered for {surface}")
    _ADAPTERS[surface] = adapter


def reset_relay_adapters_for_tests() -> None:
    _ADAPTERS.clear()


def _checkout_for_project(project_id: int) -> Path | None:
    for configured in machine_config.configured_projects(existing_only=True):
        if configured.project_id == project_id:
            return configured.checkout
    return None


def execution_context(job: Mapping[str, Any]) -> RelayExecutionContext:
    project_id = int(job.get("project_id") or 0)
    checkout = _checkout_for_project(project_id)
    if checkout is None:
        raise ValueError("relay job project has no registered checkout")
    raw_qualification = job.get("private_route_qualification")
    qualification = (
        PrivateRouteQualificationGrant.model_validate(raw_qualification)
        if raw_qualification is not None
        else None
    )
    return RelayExecutionContext(
        job_kind=str(job.get("job_kind") or ""),
        job_id=str(job.get("job_id") or ""),
        lease_id=str(job.get("lease_id") or ""),
        surface=str(job.get("surface") or ""),
        project_id=project_id,
        checkout=checkout,
        native_instruction=str(job.get("native_instruction") or ""),
        surface_version=(
            str(job["surface_version"]) if job.get("surface_version") else None
        ),
        message_id=str(job["message_id"]) if job.get("message_id") else None,
        target_session_id=(
            str(job["target_session_id"]) if job.get("target_session_id") else None
        ),
        target_native_thread_id=(
            str(job["target_native_thread_id"])
            if job.get("target_native_thread_id")
            else None
        ),
        requested_model=(
            str(job["requested_model"]) if job.get("requested_model") else None
        ),
        presentation=(str(job["presentation"]) if job.get("presentation") else None),
        session_name=(str(job["session_name"]) if job.get("session_name") else None),
        launch_deadline_at=(
            str(job["deadline_at"]) if job.get("deadline_at") else None
        ),
        target_liveness=(
            str(job["target_liveness"]) if job.get("target_liveness") else None
        ),
        wake_mode=normalize_wake_mode(job.get("wake_mode")),
        wake_route=str(job["wake_route"]) if job.get("wake_route") else None,
        launch_attestation=(
            str(job["launch_attestation"]) if job.get("launch_attestation") else None
        ),
        launch_progress_reporter=(
            job.get("_launch_progress_reporter")
            if callable(job.get("_launch_progress_reporter"))
            else None
        ),
        launch_registration_resolver=(
            job.get("_launch_registration_resolver")
            if callable(job.get("_launch_registration_resolver"))
            else None
        ),
        private_route_qualification=qualification,
    )


def run_registered_job(job: Mapping[str, Any]) -> RelayAdapterResult:
    if str(job.get("job_kind") or "") == "evidence":
        from yoke_harness.session_relay_evidence_files import read_session_evidence

        return read_session_evidence(job)
    if str(job.get("job_kind") or "") == "terminate":
        from yoke_harness.session_relay_termination import reap_terminated_session

        return reap_terminated_session(job)
    try:
        context = execution_context(job)
    except (TypeError, ValueError):
        kind = str(job.get("job_kind") or "")
        return RelayAdapterResult(
            "outcome_unknown" if kind == "launch" else "failed",
            evidence={"result_code": "checkout_unavailable"},
        )
    adapter = _ADAPTERS.get(context.surface)
    if adapter is None:
        try:
            from yoke_harness.session_relay_defaults import (
                register_default_relay_adapter,
            )

            register_default_relay_adapter(context.surface)
        except Exception:
            pass
        adapter = _ADAPTERS.get(context.surface)
    if adapter is None:
        return RelayAdapterResult(
            "not_created" if context.job_kind == "launch" else "unsupported_surface",
            evidence={
                "result_code": "adapter_unavailable",
                "surface": context.surface,
            },
        )
    try:
        return adapter(context)
    except Exception as exc:  # native failures stay private on this relay
        return RelayAdapterResult(
            "outcome_unknown" if context.job_kind == "launch" else "failed",
            evidence={"result_code": "adapter_exception", "surface": context.surface},
            private_diagnostic=RelayPrivateDiagnostic(
                "adapter_exception",
                stderr=str(exc).encode("utf-8", errors="replace"),
            ),
        )


__all__ = [
    "native_instruction_targets_job",
    "RelayAdapter",
    "RelayAdapterResult",
    "RelayExecutionContext",
    "RelayPrivateDiagnostic",
    "IDLE_TIMEOUT_WAKE_MODE",
    "WAITING_WAKE_MODE",
    "WakeMode",
    "execution_context",
    "normalize_wake_mode",
    "register_relay_adapter",
    "reset_relay_adapters_for_tests",
    "run_registered_job",
    "wake_operation",
]
