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

    try:
        health_check.fn(conn, args, rec)
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


__all__ = ["INTERNAL_ERROR_CHECK_ID", "execute_check_isolated"]
