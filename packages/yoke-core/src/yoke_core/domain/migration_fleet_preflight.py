"""Prove the pending history applies to the databases that are behind.

Copy every relevant live database, including ones behind the current history,
onto the local embedded cluster. Ordinary rehearsal executes the actual boot
sequence, schema then ordered history, before dropping the copy. Live sources
are only read. A diagnostic plan can instead inspect the faithful copy without
applying history; that result never proves boot convergence.

A --no-owner copy cannot prove live serving-role privileges; ownership is
checked against the live source before copying. Source extension versions
are pinned before restore, refusing unsupported versions rather than silently
changing the subject. See migration_fleet_preflight_extensions for fidelity.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, List, Optional, Sequence, Tuple

from yoke_core.domain import (
    migration_fleet_preflight_extensions,
    migration_fleet_preflight_transfer,
    postgres_cluster,
)
from yoke_core.domain.migration_fleet_applied_invariants import (
    format_fleet_summary,
)
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV
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
    copy_observer: Callable[[str, Path], None] | None = None
    resource_guard: Callable[[], None] | None = None
    success_detail: str = "converged"


@contextmanager
def _restore_point_named(dump: Path) -> Iterator[None]:
    """Point the applier's restore-point contract at this copy's own dump.

    The applier refuses to run a destructive entry without a named restore
    point, and it is right to. For a rehearsal the dump the copy was built
    from IS that restore point — it restores the copy to the exact state the
    run started from — so naming it satisfies the contract honestly rather
    than bypassing it.
    """
    previous = os.environ.get(RESTORE_POINT_ENV)
    os.environ[RESTORE_POINT_ENV] = str(dump)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(RESTORE_POINT_ENV, None)
        else:
            os.environ[RESTORE_POINT_ENV] = previous


def _live_ownership_verdict(
    source_dsn: str,
    database: str,
    live_ownership_validator: Callable[[Any], str | None] | None = None,
) -> Optional[Verdict]:
    """Refuse a database whose serving role cannot converge its own tables.

    Read from the live database and BEFORE the rehearsal, because the copy
    cannot answer it: ``pg_restore --no-owner`` hands everything to whoever
    restores it, so the copy always looks uniform. A rehearsal that converges
    cleanly on such a copy is a true statement about the copy and says nothing
    about the tenant — which is exactly how a green preflight preceded a
    production control plane crash-looping at boot.
    """
    from yoke_core.domain import db_backend, migration_fleet_ownership

    conn = None
    try:
        # Connecting is inside the guard on purpose: a source this cannot
        # reach must become a FAIL verdict, never an exception that escapes
        # the fleet loop and takes the other tenants' answers with it.
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
    """Converge a throwaway copy of one database and report what happened.

    Two questions, answered in two places on purpose. *Will the entries apply?*
    is answered by converging a copy, because applying them to the live
    database is the thing this exists to avoid. *Is the serving role allowed to
    apply them?* is answered against the live database, because the copy
    normalizes the ownership that decides it away.
    """
    refusal = _live_ownership_verdict(
        source_dsn,
        database,
        plan.live_ownership_validator,
    )
    if refusal is not None:
        return refusal

    # Before any data moves: a source version this cluster cannot install is a
    # copy that would silently not be the tenant, so it refuses while refusing
    # is still free.
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

    copy_name = f"{REHEARSAL_PREFIX}{database}"
    dump = work_dir / f"{database}.dump"
    work_dir.mkdir(parents=True, exist_ok=True)
    if plan.copy_observer:
        plan.copy_observer("start", dump)

    try:
        migration_fleet_preflight_transfer.dump_database(
            spec,
            source_dsn,
            dump,
            source_environment=source_environment,
            emit=_database_emit(emit, database),
            resource_guard=plan.resource_guard,
        )
        if plan.copy_observer:
            plan.copy_observer("dumped", dump)
    except Exception as exc:  # noqa: BLE001 — a verdict, not a crash
        return Verdict(database, False, f"could not copy: {exc}")

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
            resource_guard=plan.resource_guard,
        )
        if plan.copy_observer:
            plan.copy_observer("restored", dump)
        return _converge_copy(spec, database, copy_name, dump, plan)
    finally:
        try:
            if plan.copy_observer:
                plan.copy_observer("cleanup", dump)
        finally:
            migration_fleet_preflight_transfer.drop_copy(spec, copy_name)
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
        with _restore_point_named(dump):
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
            plan.success_detail if failure is None else failure,
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
