"""Rehearse the whole pending history on one faithful, read-only-source copy.

Automatic machine-wide copy admission lasts through transfer, convergence,
invariants, diagnostics, connection close and cleanup. See the copy-lock and
extension-fidelity modules for those boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

from yoke_core.domain import (
    migration_fleet_preflight_extensions,
    migration_fleet_preflight_transfer,
    migration_rehearsal_copy_lock,
    postgres_cluster,
)
from yoke_core.domain.migration_fleet_applied_invariants import (
    format_fleet_summary,
)
from yoke_core.domain.migration_restore_point import named_restore_point
from yoke_core.domain.postgres_cluster import ClusterSpec

#: Throwaway copy prefix; a leftover name is visibly disposable.
REHEARSAL_PREFIX = "migration_rehearsal_"


@dataclass(frozen=True)
class Verdict:
    """What converging one database's copy did."""

    database: str
    passed: bool
    detail: str
    pending_before: Tuple[str, ...] = ()
    applied: Tuple[str, ...] = ()
    pending_evaluated: bool = True
    skipped_invariants: Tuple[Tuple[str, str], ...] = ()

    @property
    def line(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        pending = (
            ", ".join(self.pending_before) or "nothing pending"
            if self.pending_evaluated
            else "pending not evaluated"
        )
        return f"{mark} {self.database}: {pending} -> {self.detail}"


@dataclass(frozen=True)
class RehearsalPlan:
    """Project-supplied history, ledger reader, and convergence operation."""

    history: Tuple[str, ...]
    pending_names: Callable[[Any, Sequence[str]], Tuple[str, ...]]
    converge: Callable[[Any, str], None]
    live_ownership_validator: Callable[[Any], str | None] | None = None
    #: Load one shipped history entry by ledger name so applied-history
    #: invariants can run after convergence. Absent means the caller opts
    #: out of that proof (tests that only exercise dump/ownership paths).
    load_module: Callable[[str], Any] | None = None
    post_converge_validator: Callable[[Any, str], str | None] | None = None


def _live_ownership_verdict(
    source_dsn: str,
    database: str,
    live_ownership_validator: Callable[[Any], str | None] | None = None,
) -> Optional[Verdict]:
    """Read serving-role privileges live: --no-owner copies normalize them."""
    from yoke_core.domain import db_backend, migration_fleet_ownership

    conn = None
    try:
        conn = db_backend.connect_psycopg(source_dsn)
        report = migration_fleet_ownership.inspect(conn)
        contract_detail = (
            live_ownership_validator(conn)
            if report.uniform and live_ownership_validator is not None
            else None
        )
    except Exception as exc:  # noqa: BLE001 — a verdict, not a crash
        return Verdict(
            database,
            False,
            f"could not read ownership: {exc}",
            pending_evaluated=False,
        )
    finally:
        if conn is not None:
            conn.close()
    if report.uniform:
        if contract_detail is None:
            return None
        return Verdict(
            database,
            False,
            contract_detail,
            pending_evaluated=False,
        )
    return Verdict(database, False, report.summary, pending_evaluated=False)


def rehearse(
    source_dsn: str,
    *,
    database: str,
    plan: RehearsalPlan,
    spec: ClusterSpec,
    work_dir: Path,
    source_environment: str,
    emit: Optional[Callable[[str], None]] = None,
) -> Verdict:
    """Admit one copy through cleanup; read privileges on the live database.

    A --no-owner restore normalizes ownership, so the copy cannot establish
    whether the serving role can migrate its own tables. The owned body reads
    that authority from the source before dumping it; the source is only read.
    """
    try:
        with migration_rehearsal_copy_lock.copy_lock(
            spec, f"{REHEARSAL_PREFIX}{database}"
        ):
            return _rehearse_owned(
                source_dsn,
                database=database,
                plan=plan,
                spec=spec,
                work_dir=work_dir,
                source_environment=source_environment,
                emit=emit,
            )
    except migration_rehearsal_copy_lock.RehearsalCopyBusy as exc:
        return Verdict(database, False, str(exc), pending_evaluated=False)
    except Exception as exc:  # noqa: BLE001 -- actionable fleet verdict
        detail = str(exc).replace(source_dsn, "<dsn>")
        return Verdict(
            database,
            False,
            f"rehearsal_copy_failed: {detail}; correct the failure and retry preflight",
            pending_evaluated=False,
        )


def _rehearse_owned(
    source_dsn: str,
    *,
    database: str,
    plan: RehearsalPlan,
    spec: ClusterSpec,
    work_dir: Path,
    source_environment: str,
    emit: Optional[Callable[[str], None]] = None,
) -> Verdict:
    """Copy and converge under admission; read serving privileges live."""
    refusal = _live_ownership_verdict(
        source_dsn,
        database,
        plan.live_ownership_validator,
    )
    if refusal is not None:
        return refusal

    # Refuse an unfaithful extension copy before moving data.
    try:
        pins = migration_fleet_preflight_extensions.extension_pins(
            spec,
            migration_fleet_preflight_extensions.source_extensions(source_dsn),
        )
    except Exception as exc:  # noqa: BLE001 — a verdict, not a crash
        detail = str(exc).replace(source_dsn, "<dsn>")
        return Verdict(
            database,
            False,
            f"could not copy faithfully: {detail}",
            pending_evaluated=False,
        )

    copy_name = migration_rehearsal_copy_lock.actual_database_name(
        f"{REHEARSAL_PREFIX}{database}"
    )
    dump = work_dir / f"{database}.dump"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        migration_fleet_preflight_transfer.dump_database(
            spec,
            source_dsn,
            dump,
            source_environment=source_environment,
            emit=_database_emit(emit, database),
        )
    except BaseException as exc:
        dump.unlink(missing_ok=True)  # the transfer has already stopped and reaped
        if not isinstance(exc, Exception):
            raise
        return Verdict(
            database,
            False,
            f"could not copy: {exc}; correct the failure and retry preflight",
        )

    try:
        migration_fleet_preflight_transfer.drop_copy(spec, copy_name)
        migration_fleet_preflight_transfer.create_copy(spec, copy_name)
        use_list = migration_fleet_preflight_extensions.stage_pinned_extensions(
            spec,
            copy_name,
            pins,
            dump=dump,
            list_path=work_dir / f"{database}.restore-list",
        )
        migration_fleet_preflight_transfer.restore_copy(
            spec,
            copy_name,
            dump,
            use_list=use_list,
        )
        return _converge_copy(spec, database, copy_name, dump, plan)
    finally:
        try:
            migration_fleet_preflight_transfer.drop_copy(spec, copy_name)
        finally:
            dump.unlink(missing_ok=True)


def _database_emit(
    emit: Optional[Callable[[str], None]],
    database: str,
) -> Optional[Callable[[str], None]]:
    """Prefix a copy-progress line with the database it belongs to."""
    if emit is None:
        return None
    return lambda message: emit(f"COPY/CONVERGE {database}: {message}")


def _converge_copy(
    spec: ClusterSpec,
    database: str,
    copy_name: str,
    dump: Path,
    plan: RehearsalPlan,
) -> Verdict:
    from yoke_core.domain import db_backend
    from yoke_core.domain.migration_fleet_applied_invariants import (
        AppliedInvariantReport,
        applied_shipped_names,
        verify_applied_history_invariants,
    )

    copy_dsn = postgres_cluster.dsn(spec, copy_name)
    # Boot-shaped rows (name + index). connect_psycopg stays tuple-only.
    conn = db_backend._open_native_postgres(copy_dsn)
    try:
        pending = plan.pending_names(conn, plan.history)
        with named_restore_point(dump):
            try:
                plan.converge(conn, copy_dsn)
            except BaseException as exc:  # noqa: BLE001 — a verdict, not a crash
                conn.rollback()
                return Verdict(database, False, str(exc).strip(), pending)
        applied = applied_shipped_names(plan.history, plan.pending_names, conn)
        report = (
            AppliedInvariantReport()
            if plan.load_module is None
            else verify_applied_history_invariants(
                conn,
                applied,
                history=plan.history,
                load_module=plan.load_module,
                redact=copy_dsn,
            )
        )
        failure = report.failure
        if failure is None and plan.post_converge_validator is not None:
            failure = plan.post_converge_validator(conn, copy_dsn)
        if failure is not None:
            conn.rollback()
        else:
            conn.commit()
        return Verdict(
            database,
            failure is None,
            "converged" if failure is None else failure,
            pending,
            applied,
            skipped_invariants=report.skipped,
        )
    finally:
        conn.close()


def rehearse_fleet(
    dsn_for: Callable[[str], str],
    *,
    databases: Sequence[str],
    plan: RehearsalPlan,
    spec: ClusterSpec,
    work_dir: Path,
    source_environment: str,
    emit: Optional[Callable[[str], None]] = None,
) -> List[Verdict]:
    """Rehearse the caller-declared databases with its migration plan.

    ``source_environment`` names the connection the source DSNs are reached
    through, so a copy that loses a managed forward can reopen that exact one
    before trying again.
    """
    verdicts: List[Verdict] = []
    for name in databases:
        if emit is not None:
            emit(f"COPY/CONVERGE {name}: starting rehearsal")
        verdict = rehearse(
            dsn_for(name),
            database=name,
            plan=plan,
            spec=spec,
            work_dir=work_dir,
            source_environment=source_environment,
            emit=emit,
        )
        verdicts.append(verdict)
        if emit is not None:
            emit(verdict.line)
    return verdicts


__all__ = [
    "REHEARSAL_PREFIX",
    "RehearsalPlan",
    "Verdict",
    "format_fleet_summary",
    "rehearse",
    "rehearse_fleet",
]
