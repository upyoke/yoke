"""Run one fresh relay poll, its leased batch of native jobs, and a report each."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
import logging
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.function_ids import (
    RELAY_CLAIM_FUNCTION_ID,
    RELAY_REPORT_FUNCTION_ID,
)
from yoke_harness.session_relay_diagnostic_retention import retain_private_diagnostic
from yoke_harness.session_relay_inventory import RelayInventory, collect_inventory
from yoke_harness.session_relay_process_liveness import report_verified_dead_sessions
from yoke_harness.session_relay_report_delivery import (
    RELAY_REPORT_TIMEOUT_SECONDS,
    REPORT_RETRY_SECONDS,
    checkpoint_launch_result,
    checkpoint_launch_start,
    deliver_terminal_report,
    diagnostic_outcome_fields,
    retry_pending_reports,
)
from yoke_harness.session_relay_resume_settlement import (
    settle_finished_native_resumes,
)
from yoke_harness.session_relay_runtime import RelayAdapterResult, run_registered_job
from yoke_harness.session_relay_schedule import (
    poll_is_due,
    record_next_poll,
    relay_run_lock,
)


_POLL_POLICY = FLEET_KEY_SPECS["fleet.relay_poll_seconds"]
RELAY_DISPATCH_TIMEOUT_SECONDS = int(_POLL_POLICY.default) + int(
    _POLL_POLICY.minimum or 0
)
_LOGGER = logging.getLogger(__name__)


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
    jobs: tuple[ServeOnceJobOutcome, ...] = ()


Dispatcher = Callable[..., Any]
JobRunner = Callable[[Mapping[str, Any]], RelayAdapterResult]
# Hands one leased job's settlement off to a caller that owns its lifetime.
# A caller that supplies one keeps polling while the job runs; the default
# is to settle inline, which is what a one-shot run must do.
JobDispatch = Callable[[Callable[[], "ServeOnceJobOutcome"]], None]


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


def _run_and_report(
    inventory: RelayInventory,
    job: Mapping[str, Any],
    *,
    dispatcher: Dispatcher,
    runner: JobRunner,
    state_dir: Path | None,
) -> ServeOnceJobOutcome:
    """Execute one leased job and settle it under its own lease."""
    checkpoint_launch_start(
        dispatcher,
        RELAY_REPORT_FUNCTION_ID,
        inventory.relay_id,
        job,
        timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
    )
    result = retain_private_diagnostic(
        runner(job),
        state_dir=state_dir,
        relay_id=inventory.relay_id,
        machine_id=inventory.machine_id,
    )
    result = checkpoint_launch_result(
        dispatcher,
        RELAY_REPORT_FUNCTION_ID,
        inventory.relay_id,
        job,
        result,
        timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
    )
    diagnostic_fields = diagnostic_outcome_fields(
        inventory.relay_id, inventory.machine_id, result
    )
    report = deliver_terminal_report(
        dispatcher,
        RELAY_REPORT_FUNCTION_ID,
        _report_payload(inventory, job, result),
        state_dir=state_dir,
        timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
    )
    kind = str(job.get("job_kind") or "")
    job_id = str(job.get("job_id") or "")
    if not getattr(report, "success", False):
        return ServeOnceJobOutcome(
            "report_failed",
            kind,
            job_id,
            result.result_code,
            _error_code(report),
            **diagnostic_fields,
        )
    return ServeOnceJobOutcome(
        "reported",
        kind,
        job_id,
        result.result_code,
        **diagnostic_fields,
    )


def _poll(
    inventory: RelayInventory,
    *,
    dispatcher: Dispatcher,
    runner: JobRunner,
    state_dir: Path | None = None,
    broker_only: bool = False,
    broker_lease_id: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    dispatch_job: JobDispatch | None = None,
) -> ServeOnceOutcome:
    ensure_handlers_loaded()
    if not retry_pending_reports(
        dispatcher,
        RELAY_REPORT_FUNCTION_ID,
        state_dir=state_dir,
        timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
    ):
        return ServeOnceOutcome(
            "report_failed",
            REPORT_RETRY_SECONDS,
            error_code="relay_report_pending",
        )
    settle_finished_native_resumes(
        dispatcher,
        RELAY_REPORT_FUNCTION_ID,
        relay_id=inventory.relay_id,
        machine_id=inventory.machine_id,
        state_dir=state_dir,
        timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
    )
    # A session whose native died reads stale rather than ended, so every
    # wake for it pokes a process that is gone; this machine holds the proof.
    report_verified_dead_sessions(dispatcher, inventory, state_dir=state_dir)
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
    claimed = payload.get("jobs")
    jobs = [job for job in claimed if isinstance(job, Mapping)] if claimed else []
    if not jobs:
        return ServeOnceOutcome(str(payload.get("state") or "active"), next_poll)
    # Native creates land one at a time so a burst never arrives as a spike.
    stagger = max(0, int(payload.get("launch_stagger_seconds") or 0))
    outcomes: list[ServeOnceJobOutcome] = []
    for index, job in enumerate(jobs):
        if index and stagger:
            sleep(stagger)
        settle = partial(
            _run_and_report,
            inventory,
            job,
            dispatcher=dispatcher,
            runner=runner,
            state_dir=state_dir,
        )
        if dispatch_job is not None:
            dispatch_job(settle)
            continue
        outcomes.append(settle())
    if dispatch_job is not None:
        # The jobs outlive this cycle by design, so their outcomes are not
        # this cycle's to report; the caller settles them.
        return ServeOnceOutcome("dispatched", next_poll)
    settled = tuple(outcomes)
    state = (
        "report_failed"
        if any(outcome.state == "report_failed" for outcome in settled)
        else "reported"
    )
    cadence = REPORT_RETRY_SECONDS if state == "report_failed" else next_poll
    return ServeOnceOutcome(state, cadence, jobs=settled)


def run_serve_cycle(
    *,
    state_dir: Path | None = None,
    inventory_provider: Callable[[], RelayInventory] = collect_inventory,
    inventory_refresher: Callable[[], object] | None = None,
    dispatcher: Dispatcher = call_dispatcher,
    runner: JobRunner = run_registered_job,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    broker_only: bool = False,
    broker_lease_id: str | None = None,
    dispatch_job: JobDispatch | None = None,
) -> ServeOnceOutcome:
    """Run one cadence-respecting batch inside a run lock the caller holds.

    Split from :func:`serve_once` so a caller that holds the lock for many
    cycles reuses the same transaction body. The lock is what keeps two
    relays off one machine's jobs; taking it per cycle would let a second
    process interleave between cycles of the first.
    """
    started_at = clock()
    if not broker_only and not poll_is_due(state_dir, now=started_at):
        return ServeOnceOutcome("backoff")
    inventory = inventory_provider()
    pool = ThreadPoolExecutor(max_workers=1) if inventory_refresher else None
    refresh = pool.submit(inventory_refresher) if pool else None
    try:
        outcome = _poll(
            inventory,
            dispatcher=dispatcher,
            runner=runner,
            state_dir=state_dir,
            broker_only=broker_only,
            broker_lease_id=broker_lease_id,
            sleep=sleep,
            dispatch_job=dispatch_job,
        )
    finally:
        if refresh:
            try:
                refresh.result()
            except Exception:
                _LOGGER.warning("relay surface probe refresh failed", exc_info=True)
        if pool:
            pool.shutdown()
    if outcome.next_poll_seconds and not broker_only:
        record_next_poll(
            outcome.next_poll_seconds,
            state_dir,
            started_at=started_at,
            now=clock(),
        )
    return outcome


def serve_once(
    *,
    state_dir: Path | None = None,
    inventory_provider: Callable[[], RelayInventory] = collect_inventory,
    inventory_refresher: Callable[[], object] | None = None,
    dispatcher: Dispatcher = call_dispatcher,
    runner: JobRunner = run_registered_job,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    broker_only: bool = False,
    broker_lease_id: str | None = None,
) -> ServeOnceOutcome:
    """Respect server cadence and run one bounded batch of relay transactions."""
    with relay_run_lock(state_dir) as acquired:
        if not acquired:
            return ServeOnceOutcome("locked")
        return run_serve_cycle(
            state_dir=state_dir,
            inventory_provider=inventory_provider,
            inventory_refresher=inventory_refresher,
            dispatcher=dispatcher,
            runner=runner,
            clock=clock,
            sleep=sleep,
            broker_only=broker_only,
            broker_lease_id=broker_lease_id,
        )


__all__ = [
    "RELAY_CLAIM_FUNCTION_ID",
    "RELAY_DISPATCH_TIMEOUT_SECONDS",
    "RELAY_REPORT_FUNCTION_ID",
    "RELAY_REPORT_TIMEOUT_SECONDS",
    "ServeOnceJobOutcome",
    "JobDispatch",
    "ServeOnceOutcome",
    "run_serve_cycle",
    "serve_once",
]
