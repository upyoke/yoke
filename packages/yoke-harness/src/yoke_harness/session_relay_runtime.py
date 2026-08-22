"""Closed in-process adapter registry for one relay-leased native job."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_cli.config import machine_config


@dataclass(frozen=True)
class RelayExecutionContext:
    job_kind: str
    job_id: str
    lease_id: str
    surface: str
    project_id: int
    checkout: Path
    native_instruction: str
    message_id: str | None = None
    target_session_id: str | None = None
    launch_attestation: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class RelayAdapterResult:
    result_code: str
    native_session_id: str | None = None
    adapter_revision: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)


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
    return RelayExecutionContext(
        job_kind=str(job.get("job_kind") or ""),
        job_id=str(job.get("job_id") or ""),
        lease_id=str(job.get("lease_id") or ""),
        surface=str(job.get("surface") or ""),
        project_id=project_id,
        checkout=checkout,
        native_instruction=str(job.get("native_instruction") or ""),
        message_id=str(job["message_id"]) if job.get("message_id") else None,
        target_session_id=(
            str(job["target_session_id"]) if job.get("target_session_id") else None
        ),
        launch_attestation=(
            str(job["launch_attestation"])
            if job.get("launch_attestation")
            else None
        ),
    )


def run_registered_job(job: Mapping[str, Any]) -> RelayAdapterResult:
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
        return RelayAdapterResult(
            "not_created" if context.job_kind == "launch" else "unsupported_surface",
            evidence={
                "result_code": "adapter_unavailable",
                "surface": context.surface,
            },
        )
    try:
        return adapter(context)
    except Exception:  # native failures must not leak prompts, tokens, or bodies
        return RelayAdapterResult(
            "outcome_unknown" if context.job_kind == "launch" else "failed",
            evidence={"result_code": "adapter_exception", "surface": context.surface},
        )


__all__ = [
    "RelayAdapter",
    "RelayAdapterResult",
    "RelayExecutionContext",
    "execution_context",
    "register_relay_adapter",
    "reset_relay_adapters_for_tests",
    "run_registered_job",
]
