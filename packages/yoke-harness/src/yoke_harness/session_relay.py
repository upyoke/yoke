"""Run one fresh relay poll, at most one native job, and one report."""

from __future__ import annotations

from dataclasses import dataclass
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


Dispatcher = Callable[..., Any]
JobRunner = Callable[[Mapping[str, Any]], RelayAdapterResult]


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


def _poll(
    inventory: RelayInventory,
    *,
    dispatcher: Dispatcher,
    runner: JobRunner,
    broker_only: bool = False,
) -> ServeOnceOutcome:
    ensure_handlers_loaded()
    response = dispatcher(
        function_id=RELAY_CLAIM_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload=inventory.claim_payload(
            wait_seconds=0 if broker_only else None,
            broker_only=broker_only,
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
    result = runner(job)
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
        )
    return ServeOnceOutcome(
        "reported",
        next_poll,
        kind,
        job_id,
        result.result_code,
    )


def serve_once(
    *,
    state_dir: Path | None = None,
    inventory_provider: Callable[[], RelayInventory] = collect_inventory,
    dispatcher: Dispatcher = call_dispatcher,
    runner: JobRunner = run_registered_job,
    clock: Callable[[], float] = time.time,
    broker_only: bool = False,
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
            broker_only=broker_only,
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
