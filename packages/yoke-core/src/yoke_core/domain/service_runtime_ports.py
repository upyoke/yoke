"""Execution interfaces used at the service boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol, cast

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.runtime_ports.loader import load_port


class DoctorRun(Protocol):
    """Execute health checks for an already dispatched request."""

    def run(self, request: FunctionCallRequest) -> HandlerOutcome: ...


def get_doctor_run() -> DoctorRun:
    return cast(DoctorRun, load_port("doctor_run", DoctorRun))


class RemoteHookEvaluator(Protocol):
    """Evaluate a relayed request with the installed hook runtime."""

    evaluate_remote: Callable[..., Any]


def get_remote_hook_evaluator() -> RemoteHookEvaluator:
    return cast(
        RemoteHookEvaluator, load_port("remote_hook_evaluator", RemoteHookEvaluator)
    )


class HookRunner(Protocol):
    """Run one hook event through the local runner."""

    main: Callable[[list[str]], int]


def get_hook_runner() -> HookRunner:
    return cast(HookRunner, load_port("hook_runner", HookRunner))


class HookServiceRuntime(Protocol):
    """Hook effects and observations carried by the service routes."""

    def confirmed_title(
        self, session_id: str | None, payload: Mapping[str, Any]
    ) -> dict[str, Any] | None: ...

    def confirmed_served_model(
        self, session_id: str | None, model: str | None
    ) -> str | None: ...

    def persist_authorization_denied_turn_end(
        self, *, event_name: str, session_id: str, actor_id: int, observed_at: datetime
    ) -> str | None: ...

    request_payload: Callable[..., tuple[Any, dict[str, Any]]]
    persist_observation_batch: Callable[..., tuple[int, dict[str, Any]]]


def get_hook_service_runtime() -> HookServiceRuntime:
    return cast(
        HookServiceRuntime, load_port("hook_service_runtime", HookServiceRuntime)
    )


class HookDenial(Protocol):
    """Record a hook refusal and close its tool-call telemetry when requested."""

    emit_denial_event: Callable[..., Any]


def get_hook_denial() -> HookDenial:
    return cast(HookDenial, load_port("hook_denial", HookDenial))
