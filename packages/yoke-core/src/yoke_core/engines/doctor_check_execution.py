"""Transaction-isolated execution for one Doctor health check.

Doctor reuses one database connection across its roster.  PostgreSQL marks
that connection's transaction as aborted after a statement error, including
errors swallowed by a check's best-effort probe.  Resetting the transaction
before and after every check keeps one check's database state from changing
the verdicts produced by later checks.
"""

from __future__ import annotations

from typing import Any

from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


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
    try:
        _rollback_if_supported(conn)
    except Exception as exc:  # pragma: no cover - broken connection guard
        rec.record(
            f"HC-{health_check.slug}",
            health_check.name,
            "FAIL",
            f"Internal error: could not isolate check transaction: {exc}",
        )
        return

    try:
        health_check.fn(conn, args, rec)
    except Exception as exc:
        detail = f"Internal error: {exc}"
        try:
            _rollback_if_supported(conn)
        except Exception as rollback_exc:  # pragma: no cover - broken connection guard
            detail += f"; transaction recovery also failed: {rollback_exc}"
        rec.record(
            f"HC-{health_check.slug}", health_check.name, "FAIL", detail,
        )
        return

    try:
        _rollback_if_supported(conn)
    except Exception as exc:  # pragma: no cover - broken connection guard
        rec.record(
            f"HC-{health_check.slug}",
            health_check.name,
            "FAIL",
            f"Internal error: could not close check transaction: {exc}",
        )


__all__ = ["execute_check_isolated"]
