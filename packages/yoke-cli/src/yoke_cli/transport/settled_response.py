"""Settle released Test Machines from the CLI that holds their credentials."""

from __future__ import annotations

from contextvars import ContextVar
import importlib
import shlex
import sys
from typing import Sequence

from yoke_cli.transport.public_ref_display import redact_response
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.refusal_recovery import compose_refusal


# Nested operation releases still settle power, but cannot start another reset.
_settling_release = ContextVar("settling_test_machine_release", default=False)


def settle_response(
    response: FunctionCallResponse, sensitive_values: Sequence[str] = (), *, actor=None, relay_env=None
) -> FunctionCallResponse:
    response = redact_response(response, tuple(sensitive_values))
    if not (response.test_machines_to_stop or response.test_machines_to_reset):
        return response
    nested = _settling_release.get()
    token = _settling_release.set(True)
    try:
        if response.test_machines_to_stop:
            _stop_released(response.test_machines_to_stop, actor=actor, relay_env=relay_env)
        if not nested:
            for machine in response.test_machines_to_reset:
                _reset_released(machine, actor=actor, relay_env=relay_env)
    finally:
        _settling_release.reset(token)
    return response


def _stop_released(machines, *, actor, relay_env):
    try:
        stop = importlib.import_module("yoke_core.domain.machine_idle_stop")
    except ImportError as exc:
        refusal = compose_refusal(
            "test_machine_power_stop_failed: cloud Test Machines "
            f"{machines} stay running; this CLI cannot load the stop ({exc})",
            recovery="run `yoke update`, then `yoke test-machine verify`, "
            "whose release stops them",
        )
        print(refusal, file=sys.stderr, flush=True)
    else:
        stop.stop_released(machines, actor=actor, relay_env=relay_env)


def _reset_released(machine, *, actor, relay_env):
    name, baseline = machine["test_machine"], machine["baseline"]
    try:
        from yoke_cli.commands.adapters.test_machine_operation import _run

        response = _run(
            operation="reset", test_machine=name, baseline=baseline,
            actor=actor, relay_env=relay_env, automatic_reset=True,
        )
        if response.error is not None:
            failure = response.error
            if failure.message.startswith("automatic_reset_skipped:"):
                return
            code, detail = failure.code, failure.message
        elif response.result.get("status") == "verified":
            return
        else:
            code = response.result.get("error_code") or "machine_needs_repair"
            detail = "reset did not return a verified receipt"
    except Exception as exc:  # noqa: BLE001 - a reset never masks its call
        from yoke_contracts.machine_qa_failures import host_control_failure

        code, detail, _ = host_control_failure(exc, phase="automatic_reset")
    manual = shlex.join(["yoke", "test-machine", "reset", "--test-machine", name, "--baseline", baseline])
    print(
        compose_refusal(f"{code}: automatic reset of {name} failed: {detail}", recovery=f"run `{manual}`"),
        file=sys.stderr,
        flush=True,
    )


__all__ = ["settle_response"]
