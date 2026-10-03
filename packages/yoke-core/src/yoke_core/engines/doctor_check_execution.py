"""Transaction-isolated execution for one Doctor health check.

Doctor reuses one database connection across its roster.  PostgreSQL marks
that connection's transaction as aborted after a statement error, including
errors swallowed by a check's best-effort probe.  Resetting the transaction
before and after every check keeps one check's database state from changing
the verdicts produced by later checks.

Every runner that executes a check goes through here, so this is also
where a run's per-check progress lines are emitted (see
:mod:`yoke_core.engines.doctor_progress`).  Emitting at the seam rather
than in each caller's loop is what keeps the engine entrypoint, the
``doctor.run.run`` handler, and the client-side composition passes of a
relayed run all reporting progress without any of them remembering to.
The lines are silent unless a caller installed a sink.
"""

from __future__ import annotations

from typing import Any
import sys
import threading

from yoke_contracts.doctor_budget import (
    CHECK_BUDGET_S,
    DoctorBudgetExhausted,
    check_budget,
    remaining_seconds,
)

from yoke_contracts.control_plane_locality import RemoteControlPlaneConnectionError
from yoke_core.engines import doctor_progress
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


INTERNAL_ERROR_CHECK_ID = "HC-internal-error"


def _rollback_if_supported(conn: Any) -> None:
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        rollback()


def execute_check_isolated(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
    health_check: HealthCheck,
) -> None:
    """Run one HC with clean transaction boundaries.

    Successful writes made by ``--fix`` checks remain durable because those
    checks commit explicitly.  Any uncommitted read transaction or aborted
    best-effort probe is discarded before the next HC starts.
    """
    recorded_before = len(rec.results)
    doctor_progress.check_started(health_check.slug)
    try:
        _run_isolated(conn, args, rec, health_check)
    finally:
        for record in rec.results[recorded_before:]:
            doctor_progress.check_finished(record.check_id, record.result)


def _run_isolated(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
    health_check: HealthCheck,
) -> None:
    """Execute the check body, recording any internal failure as a verdict."""
    try:
        _rollback_if_supported(conn)
    except Exception as exc:  # pragma: no cover - broken connection guard
        rec.record(
            INTERNAL_ERROR_CHECK_ID,
            health_check.name,
            "FAIL",
            f"Internal error isolating {health_check.slug}: {exc}",
        )
        return

    recorded_before = len(rec.results)
    try:
        with check_budget():
            _run_bounded(conn, args, rec, health_check)
    except DoctorBudgetExhausted:
        _rollback_if_supported(conn)
        for row in rec.results[recorded_before:]:
            if row.result == "PASS":
                row.result = "FAIL"
                row.detail = "Incomplete check: " + row.detail
        rec.record(
            "HC-check-incomplete",
            health_check.name,
            "FAIL",
            f"doctor_check_budget_exhausted: {health_check.slug} exceeded "
            f"its {CHECK_BUDGET_S:g}s check budget; evidence is incomplete. "
            f"Recovery: retry `yoke watch doctor -- --only {health_check.slug}` "
            "after the named database or provider recovers; narrow or optimize "
            "the check if the budget is exhausted again.",
        )
        return
    except RemoteControlPlaneConnectionError as exc:
        detail = (
            f"Control-plane locality refusal in {health_check.slug} "
            f"({type(exc).__name__}): {exc} Recovery: reach control-plane "
            "rows through a registered function-call read, or, only when "
            "this check intentionally opens a separate local database it "
            "owns, declare the connection call site with "
            "yoke_contracts.control_plane_locality.local_authority_exempt()."
        )
        try:
            _rollback_if_supported(conn)
        except Exception as rollback_exc:  # pragma: no cover - broken connection guard
            detail += f" Transaction recovery also failed: {rollback_exc}"
        rec.record(INTERNAL_ERROR_CHECK_ID, health_check.name, "FAIL", detail)
        return
    except Exception as exc:
        detail = f"Internal error in {health_check.slug}: {exc}"
        try:
            _rollback_if_supported(conn)
        except Exception as rollback_exc:  # pragma: no cover - broken connection guard
            detail += f"; transaction recovery also failed: {rollback_exc}"
        rec.record(INTERNAL_ERROR_CHECK_ID, health_check.name, "FAIL", detail)
        return

    try:
        _rollback_if_supported(conn)
    except Exception as exc:  # pragma: no cover - broken connection guard
        rec.record(
            INTERNAL_ERROR_CHECK_ID,
            health_check.name,
            "FAIL",
            f"Internal error closing {health_check.slug}: {exc}",
        )


def _run_bounded(conn, args, rec, health_check):
    """Interrupt Python work and cancel a blocked database query at the bound.

    No abandoned check thread can keep running a --fix after we answer. The
    trace belongs to this executing thread; HTTP and subprocess transports
    consume the same context deadline for blocking work.
    """
    previous_trace = sys.gettrace()
    ticks = 0

    def trace(frame, event, arg):
        nonlocal ticks
        ticks += 1
        if ticks % 256 == 0:
            remaining_seconds(CHECK_BUDGET_S)
        if previous_trace:
            previous_trace(frame, event, arg)
        return trace

    cancel = getattr(conn, "cancel_safe", None)
    postgres_cancel = callable(cancel)
    if not callable(cancel):
        cancel = getattr(conn, "interrupt", None)
    timer = None
    if callable(cancel):

        def cancel_query():
            try:
                cancel(timeout=1) if postgres_cancel else cancel()
            except Exception:
                pass  # The executing thread still reports its budget failure.

        timer = threading.Timer(remaining_seconds(CHECK_BUDGET_S), cancel_query)
        timer.daemon = True
        timer.start()
    try:
        sys.settrace(trace)
        health_check.fn(conn, args, rec)
    finally:
        sys.settrace(previous_trace)
        if timer:
            timer.cancel()
            timer.join()


__all__ = ["INTERNAL_ERROR_CHECK_ID", "execute_check_isolated"]
