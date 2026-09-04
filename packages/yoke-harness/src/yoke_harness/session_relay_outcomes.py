"""Body-free outcomes returned by one machine-relay poll."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServeOnceJobOutcome:
    """One job's sanitized result; never carries prompts, bodies, or tokens."""

    state: str
    job_kind: str | None = None
    job_id: str | None = None
    result_code: str | None = None
    error_code: str | None = None
    relay_id: str | None = None
    machine_id: str | None = None
    native_diagnostic_ref: str | None = None
    native_diagnostic_command: str | None = None
    diagnostic_expires_at: int | None = None
    diagnostic_availability: str | None = None
    native_error_class: str | None = None
    native_error_step: str | None = None


@dataclass(frozen=True)
class ServeOnceOutcome:
    """Sanitized process outcome; never carries prompts, bodies, or tokens."""

    state: str
    next_poll_seconds: int = 0
    error_code: str | None = None
    error_detail: str | None = None
    local_revision: str | None = None
    server_revision: str | None = None
    recovery: str | None = None
    jobs: tuple[ServeOnceJobOutcome, ...] = ()


__all__ = ["ServeOnceJobOutcome", "ServeOnceOutcome"]
