"""Run one fresh relay poll, at most one native job, and one report."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.function_ids import RELAY_FUNCTION_IDS
from yoke_harness.session_relay_inventory import RelayInventory, collect_inventory
from yoke_harness.session_relay_native_diagnostics import (
    NativeDiagnosticError,
    store_native_diagnostic,
)
from yoke_harness.session_relay_runtime import RelayAdapterResult, run_registered_job
from yoke_harness.session_relay_schedule import (
    poll_is_due,
    record_next_poll,
    relay_run_lock,
)


RELAY_CLAIM_FUNCTION_ID, RELAY_REPORT_FUNCTION_ID = RELAY_FUNCTION_IDS[1:]
_POLL_POLICY = FLEET_KEY_SPECS["fleet.relay_poll_seconds"]
RELAY_DISPATCH_TIMEOUT_SECONDS = int(_POLL_POLICY.default) + int(
    _POLL_POLICY.minimum or 0
)
RELAY_REPORT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ServeOnceOutcome:
    """Sanitized process outcome; never carries prompts, bodies, or tokens."""

    state: str
    next_poll_seconds: int = 0
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


Dispatcher = Callable[..., Any]
JobRunner = Callable[[Mapping[str, Any]], RelayAdapterResult]
_NATIVE_FAILURE_CLASSES = frozenset(
    {
        "adapter_exception",
        "background_session_in_use",
        "native_exception",
        "no_conversation_found",
        "process_exit",
    }
)
_NATIVE_ERROR_STEPS = frozenset(
    {
        "launch",
        "native_command",
        "resume",
        "session_lookup",
        "session_stop",
        "state_poll",
    }
)


def _error_code(response: Any) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "code", None) or "relay_dispatch_failed")


def _report_payload(
    inventory: RelayInventory,
    job: Mapping[str, Any],
    result: RelayAdapterResult,
) -> dict[str, object]:
    return {
        "relay_id": inventory.relay_id,
        "job_kind": str(job.get("job_kind") or ""),
        "job_id": str(job.get("job_id") or ""),
        "lease_id": str(job.get("lease_id") or ""),
        "result": result.result_code,
        "native_id": result.native_session_id,
        "adapter_revision": result.adapter_revision,
        "evidence": redacted_evidence_document(result.evidence),
    }


def _retain_private_diagnostic(
    result: RelayAdapterResult,
    *,
    state_dir: Path | None,
    inventory: RelayInventory | None = None,
) -> RelayAdapterResult:
    private = result.private_diagnostic
    if private is None:
        return result
    failure_class = (
        private.failure_class
        if private.failure_class in _NATIVE_FAILURE_CLASSES
        else "adapter_exception"
    )
    evidence = dict(result.evidence)
    evidence["native_error_class"] = failure_class
    evidence["native_error_step"] = (
        private.error_step
        if private.error_step in _NATIVE_ERROR_STEPS
        else "native_command"
    )
    if inventory is not None:
        evidence["relay_id"] = inventory.relay_id
        evidence["machine_id"] = inventory.machine_id
    try:
        receipt = store_native_diagnostic(
            private.stdout,
            private.stderr,
            state_dir=state_dir,
        )
    except NativeDiagnosticError:
        evidence["diagnostic_availability"] = "unavailable"
    else:
        evidence.update(
            {
                "diagnostic_availability": "relay_local",
                "diagnostic_expires_at": receipt.expires_at,
                "native_diagnostic_ref": receipt.reference,
                "native_error_sha256": receipt.fingerprint_sha256,
            }
        )
    return replace(result, evidence=evidence, private_diagnostic=None)


def _diagnostic_outcome_fields(
    inventory: RelayInventory,
    result: RelayAdapterResult,
) -> dict[str, object]:
    evidence = redacted_evidence_document(result.evidence)
    reference = evidence.get("native_diagnostic_ref")
    failure_class = evidence.get("native_error_class")
    availability = evidence.get("diagnostic_availability")
    if not any((reference, failure_class, availability)):
        return {}
    return {
        "relay_id": inventory.relay_id,
        "machine_id": inventory.machine_id,
        "native_diagnostic_ref": reference if isinstance(reference, str) else None,
        "native_diagnostic_command": evidence.get("native_diagnostic_command"),
        "diagnostic_expires_at": evidence.get("diagnostic_expires_at"),
        "diagnostic_availability": availability,
        "native_error_class": failure_class,
        "native_error_step": evidence.get("native_error_step"),
    }


def _poll(
    inventory: RelayInventory,
    *,
    dispatcher: Dispatcher,
    runner: JobRunner,
    state_dir: Path | None = None,
    broker_only: bool = False,
    broker_lease_id: str | None = None,
) -> ServeOnceOutcome:
    ensure_handlers_loaded()
    response = dispatcher(
        function_id=RELAY_CLAIM_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload=inventory.claim_payload(
            wait_seconds=0 if broker_only else None,
            broker_only=broker_only,
            broker_lease_id=broker_lease_id,
        ),
        timeout_s=RELAY_DISPATCH_TIMEOUT_SECONDS,
    )
    if not getattr(response, "success", False):
        return ServeOnceOutcome("claim_failed", error_code=_error_code(response))
    payload = getattr(response, "result", None) or {}
    next_poll = max(1, int(payload.get("next_poll_seconds") or 1))
    job = payload.get("job")
    if not isinstance(job, Mapping):
        return ServeOnceOutcome(str(payload.get("state") or "active"), next_poll)
    result = _retain_private_diagnostic(
        runner(job),
        state_dir=state_dir,
        inventory=inventory,
    )
    diagnostic_fields = _diagnostic_outcome_fields(inventory, result)
    report = dispatcher(
        function_id=RELAY_REPORT_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload=_report_payload(inventory, job, result),
        timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
    )
    kind = str(job.get("job_kind") or "")
    job_id = str(job.get("job_id") or "")
    if not getattr(report, "success", False):
        return ServeOnceOutcome(
            "report_failed",
            next_poll,
            kind,
            job_id,
            result.result_code,
            _error_code(report),
            **diagnostic_fields,
        )
    return ServeOnceOutcome(
        "reported",
        next_poll,
        kind,
        job_id,
        result.result_code,
        **diagnostic_fields,
    )


def serve_once(
    *,
    state_dir: Path | None = None,
    inventory_provider: Callable[[], RelayInventory] = collect_inventory,
    dispatcher: Dispatcher = call_dispatcher,
    runner: JobRunner = run_registered_job,
    clock: Callable[[], float] = time.time,
    broker_only: bool = False,
    broker_lease_id: str | None = None,
) -> ServeOnceOutcome:
    """Respect server cadence and run a single bounded relay transaction."""
    started_at = clock()
    with relay_run_lock(state_dir) as acquired:
        if not acquired:
            return ServeOnceOutcome("locked")
        if not broker_only and not poll_is_due(state_dir, now=started_at):
            return ServeOnceOutcome("backoff")
        outcome = _poll(
            inventory_provider(),
            dispatcher=dispatcher,
            runner=runner,
            state_dir=state_dir,
            broker_only=broker_only,
            broker_lease_id=broker_lease_id,
        )
        if outcome.next_poll_seconds and not broker_only:
            record_next_poll(
                outcome.next_poll_seconds,
                state_dir,
                started_at=started_at,
                now=clock(),
            )
        return outcome


__all__ = [
    "RELAY_CLAIM_FUNCTION_ID",
    "RELAY_DISPATCH_TIMEOUT_SECONDS",
    "RELAY_REPORT_FUNCTION_ID",
    "RELAY_REPORT_TIMEOUT_SECONDS",
    "ServeOnceOutcome",
    "serve_once",
]
