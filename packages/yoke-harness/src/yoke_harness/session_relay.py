"""Run one fresh relay poll, its leased batch of native jobs, and a report each."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
from yoke_contracts.session_control.relay_health import (
    RELAY_NEWER_THAN_SERVER,
    RELAY_NEWER_THAN_SERVER_RECOVERY,
)
from yoke_harness.session_relay_diagnostic_retention import retain_private_diagnostic
from yoke_harness.session_relay_build_compatibility import (
    refresh_relay_build_compatibility,
    refusal_from_health,
)
from yoke_harness.session_relay_health import observe_relay_health
from yoke_harness.session_relay_inventory import RelayInventory, collect_inventory
from yoke_harness.session_relay_launch_settlement import (
    report_unregistered_launch_deaths,
)
from yoke_harness.session_relay_claude_idle_hosts import reclaim_idle_claude_hosts
from yoke_harness.session_relay_native_turn_end import report_native_turn_ends
from yoke_harness.session_relay_outcomes import ServeOnceJobOutcome, ServeOnceOutcome
from yoke_harness.session_relay_process_liveness import report_verified_dead_sessions
from yoke_harness.session_relay_report_delivery import (
    RELAY_REPORT_TIMEOUT_SECONDS,
    REPORT_RETRY_SECONDS,
    checkpoint_launch_result,
    checkpoint_launch_start,
    deliver_terminal_report,
    diagnostic_outcome_fields,
)
from yoke_harness.session_relay_report_retry import retry_pending_reports
from yoke_harness.session_relay_resume_settlement import settle_finished_native_resumes
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


Dispatcher = Callable[..., Any]
JobRunner = Callable[[Mapping[str, Any]], RelayAdapterResult]
JobDispatch = Callable[[Callable[[], "ServeOnceJobOutcome"]], None]


def _error_code(response: Any) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "code", None) or "relay_dispatch_failed")


def _report_payload(
    inventory: RelayInventory, job: Mapping[str, Any], result: RelayAdapterResult
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
        "document": result.document,
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
    job = checkpoint_launch_start(
        dispatcher,
        RELAY_REPORT_FUNCTION_ID,
        inventory.relay_id,
        job,
        timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
    )
    result = retain_private_diagnostic(
        runner(job),
        attempt_id=str(job.get("job_id") or ""),
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
    dispatch_job: JobDispatch | None = None,
) -> ServeOnceOutcome:
    ensure_handlers_loaded()
    inventory = replace(inventory, relay_health=observe_relay_health(state_dir))
    refusal = refusal_from_health(inventory.relay_health)
    if refusal is not None:
        return ServeOnceOutcome(
            RELAY_NEWER_THAN_SERVER,
            int(_POLL_POLICY.default),
            error_code=RELAY_NEWER_THAN_SERVER,
            error_detail=refusal.message,
            local_revision=refusal.local_revision,
            server_revision=refusal.server_revision,
            recovery=RELAY_NEWER_THAN_SERVER_RECOVERY,
        )
    reports_drained = retry_pending_reports(
        dispatcher,
        RELAY_REPORT_FUNCTION_ID,
        state_dir=state_dir,
        timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
    )
    inventory = replace(inventory, relay_health=observe_relay_health(state_dir))
    if not reports_drained:
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
    # A native that died reads stale rather than ended; this machine has proof.
    report_verified_dead_sessions(dispatcher, inventory, state_dir=state_dir)
    # One that died before registering has no session to read at all, and its
    # launch would otherwise wait out the whole registration deadline.
    report_unregistered_launch_deaths(dispatcher, inventory, state_dir=state_dir)
    reclaim_idle_claude_hosts(dispatcher, inventory)
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
    # A turn that ended with no hook to say so left a posture nothing wakes.
    report_native_turn_ends(dispatcher, inventory, payload.get("turn_end_probes"))
    next_poll = max(1, int(payload.get("next_poll_seconds") or 1))
    claimed = payload.get("jobs")
    jobs = [job for job in claimed if isinstance(job, Mapping)] if claimed else []
    if not jobs:
        return ServeOnceOutcome(str(payload.get("state") or "active"), next_poll)
    outcomes: list[ServeOnceJobOutcome] = []
    for job in jobs:
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
    dispatcher: Dispatcher | None = None,
    runner: JobRunner = run_registered_job,
    clock: Callable[[], float] = time.time,
    broker_only: bool = False,
    broker_lease_id: str | None = None,
    dispatch_job: JobDispatch | None = None,
) -> ServeOnceOutcome:
    """Run one cadence-respecting batch inside a run lock the caller holds.

    Split from :func:`serve_once` so a caller holding the lock for many cycles
    reuses one body. The lock keeps two relays off one machine's jobs; taking
    it per cycle would let a second process interleave between cycles.
    """
    started_at = clock()
    if not broker_only and not poll_is_due(state_dir, now=started_at):
        return ServeOnceOutcome("backoff")
    default_dispatcher = dispatcher is None
    dispatcher = dispatcher or call_dispatcher
    if default_dispatcher:
        refresh_relay_build_compatibility(
            dispatcher,
            state_dir=state_dir,
            timeout_s=RELAY_REPORT_TIMEOUT_SECONDS,
        )
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
    dispatcher: Dispatcher | None = None,
    runner: JobRunner = run_registered_job,
    clock: Callable[[], float] = time.time,
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
