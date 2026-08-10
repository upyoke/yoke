"""Prove the pending history applies to the databases that are behind.

Rehearsing an entry against a current database proves nothing about the
installs that need it, because a current database has nothing pending. The
universes an entry exists for are exactly the ones behind it, and the only
way to learn whether it still applies to them is to run it against one.

Against a *copy* of one: the entries here are the real ones, and a rehearsal
that could damage its own subject would be a worse outage than the one it
prevents. Each database is dumped, restored onto the local embedded cluster,
converged exactly as a booting container converges it, and dropped. The live
database is only ever read.

The converge is the whole sequence — schema first, then history — because
the schema step is what an entry actually meets. An entry authored a year ago
runs against every constraint added since, and only the real ordering shows
whether it survives them.

**What a copy can and cannot prove.** It proves schema and data: that the
entries apply to these rows in this shape. It proves nothing about anything
``pg_restore`` normalizes, and it normalizes ownership and privileges — every
object in a ``--no-owner`` restore belongs to whoever restored it. So a copy
cannot answer whether the *serving role* is permitted to converge its own
tables, and that question has its own failure mode: a table created by another
role can never afterwards gain a column, which fails a boot rather than a
migration. Ownership is therefore read from the live database, before the
rehearsal, in :func:`_live_ownership_verdict`. Anything else a copy silently
normalizes belongs there too.
"""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, List, Optional, Sequence, Tuple

from yoke_core.domain import postgres_cluster
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV
from yoke_core.domain.postgres_cluster import ClusterSpec

#: Prefix for the throwaway copy a rehearsal converges. Names it clearly
#: enough that an operator who finds one left behind knows it is disposable.
REHEARSAL_PREFIX = "migration_rehearsal_"

#: Seconds allowed for one dump or restore. Tenant databases are small, but
#: the dump crosses a tunnel to a managed cluster.
TRANSFER_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class Verdict:
    """What converging one database's copy did."""

    database: str
    passed: bool
    detail: str
    pending_before: Tuple[str, ...] = ()
    applied: Tuple[str, ...] = ()
    pending_evaluated: bool = True

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


def _run(argv: Sequence[str], *, redact: str = "") -> None:
    result = subprocess.run(
        list(argv), capture_output=True, text=True, timeout=TRANSFER_TIMEOUT_SECONDS
    )
    if result.returncode == 0:
        return
    # The source DSN is an argument, so the failing command can quote it back.
    stderr = (result.stderr or "").strip()
    if redact:
        stderr = stderr.replace(redact, "<dsn>")
    raise RuntimeError(f"{Path(argv[0]).name} failed ({result.returncode}): {stderr}")


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

    copy_name = f"{REHEARSAL_PREFIX}{database}"
    dump = work_dir / f"{database}.dump"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        _run(
            [
                postgres_cluster.binary(spec, "pg_dump"),
                "--no-owner",
                "--no-privileges",
                "--format=custom",
                "--file",
                str(dump),
                source_dsn,
            ],
            redact=source_dsn,
        )
    except Exception as exc:  # noqa: BLE001 — a verdict, not a crash
        return Verdict(database, False, f"could not copy: {exc}")

    try:
        _drop_copy(spec, copy_name)
        _run(
            [
                postgres_cluster.binary(spec, "createdb"),
                "-h",
                str(spec.sock_dir),
                "-U",
                spec.superuser,
                copy_name,
            ]
        )
        _run(
            [
                postgres_cluster.binary(spec, "pg_restore"),
                "-h",
                str(spec.sock_dir),
                "-U",
                spec.superuser,
                "-d",
                copy_name,
                "--no-owner",
                "--no-privileges",
                str(dump),
            ]
        )
        return _converge_copy(spec, database, copy_name, dump, plan)
    finally:
        _drop_copy(spec, copy_name)
        dump.unlink(missing_ok=True)


def _converge_copy(
    spec: ClusterSpec,
    database: str,
    copy_name: str,
    dump: Path,
    plan: RehearsalPlan,
) -> Verdict:
    from yoke_core.domain import db_backend
    from yoke_core.domain.migration_fleet_applied_invariants import (
        applied_shipped_names,
        verify_applied_history_invariants,
    )

    copy_dsn = postgres_cluster.dsn(spec, copy_name)
    conn = db_backend.connect_psycopg(copy_dsn)
    try:
        pending = plan.pending_names(conn, plan.history)
        with _restore_point_named(dump):
            try:
                plan.converge(conn, copy_dsn)
            except BaseException as exc:  # noqa: BLE001 — a verdict, not a crash
                conn.rollback()
                return Verdict(database, False, str(exc).strip(), pending)
        applied = applied_shipped_names(plan.history, plan.pending_names, conn)
        failure = (
            None
            if plan.load_module is None
            else verify_applied_history_invariants(
                conn, applied, load_module=plan.load_module, redact=copy_dsn
            )
        )
        if failure is not None:
            conn.rollback()
            return Verdict(database, False, failure, pending, applied)
        conn.commit()
        return Verdict(database, True, "converged", pending, applied)
    finally:
        conn.close()


def _drop_copy(spec: ClusterSpec, copy_name: str) -> None:
    subprocess.run(
        [
            postgres_cluster.binary(spec, "dropdb"),
            "-h",
            str(spec.sock_dir),
            "-U",
            spec.superuser,
            "--if-exists",
            "--force",
            copy_name,
        ],
        capture_output=True,
        text=True,
        timeout=TRANSFER_TIMEOUT_SECONDS,
    )


def rehearse_fleet(
    dsn_for: Callable[[str], str],
    *,
    databases: Sequence[str],
    plan: RehearsalPlan,
    spec: ClusterSpec,
    work_dir: Path,
) -> List[Verdict]:
    """Rehearse the caller-declared databases with its migration plan."""
    return [
        rehearse(
            dsn_for(name),
            database=name,
            plan=plan,
            spec=spec,
            work_dir=work_dir,
        )
        for name in databases
    ]


__all__ = [
    "REHEARSAL_PREFIX",
    "RehearsalPlan",
    "Verdict",
    "rehearse",
    "rehearse_fleet",
]
