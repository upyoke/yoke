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

#: The platform service's own database, which is not a tenant universe.
PLATFORM_DATABASE = "yoke_platform"

#: Prefix for the throwaway copy a rehearsal converges. Names it clearly
#: enough that an operator who finds one left behind knows it is disposable.
REHEARSAL_PREFIX = "yoke_migration_rehearsal_"

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

    @property
    def line(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        pending = ", ".join(self.pending_before) or "nothing pending"
        return f"{mark} {self.database}: {pending} -> {self.detail}"


def tenant_databases(dsn_for: Callable[[str], str]) -> List[str]:
    """Every tenant database on the cluster, the platform database excluded."""
    import psycopg

    with psycopg.connect(dsn_for(PLATFORM_DATABASE), connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false AND datname LIKE 'yoke_%' "
                "ORDER BY datname"
            )
            return [r[0] for r in cur.fetchall() if r[0] != PLATFORM_DATABASE]


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


def _pending_names(conn: Any, history_names: Sequence[str]) -> Tuple[str, ...]:
    """History entries this database has no ledger row for.

    A missing ledger table and an empty one both mean the whole history is
    pending. They are different facts about how the database got there, and
    the same fact about what happens next.
    """
    cur = conn.execute("SELECT to_regclass('applied_migrations')")
    if cur.fetchone()[0] is None:
        return tuple(history_names)
    rows = conn.execute("SELECT migration_name FROM applied_migrations").fetchall()
    applied = {r[0] for r in rows}
    return tuple(name for name in history_names if name not in applied)


def _history_names() -> Tuple[str, ...]:
    from yoke_core.domain import migrations as history_package
    from yoke_core.domain.migration_history import history_dir, ordered_entries

    return tuple(e.name for e in ordered_entries(history_dir(history_package)))


def rehearse(
    source_dsn: str,
    *,
    database: str,
    spec: ClusterSpec,
    work_dir: Path,
) -> Verdict:
    """Converge a throwaway copy of one database and report what happened."""
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
        _run([postgres_cluster.binary(spec, "createdb"), "-h",
              str(spec.sock_dir), "-U", spec.superuser, copy_name])
        _run([postgres_cluster.binary(spec, "pg_restore"), "-h", str(spec.sock_dir),
              "-U", spec.superuser, "-d", copy_name, "--no-owner",
              "--no-privileges", str(dump)])
        return _converge_copy(spec, database, copy_name, dump)
    finally:
        _drop_copy(spec, copy_name)
        dump.unlink(missing_ok=True)


def _converge_copy(
    spec: ClusterSpec, database: str, copy_name: str, dump: Path
) -> Verdict:
    from yoke_core.domain import db_backend
    from yoke_core.domain.schema_init import converge_core_schema

    conn = db_backend.connect_psycopg(postgres_cluster.dsn(spec, copy_name))
    try:
        history = _history_names()
        pending = _pending_names(conn, history)
        with _restore_point_named(dump):
            try:
                converge_core_schema(conn)
            except BaseException as exc:  # noqa: BLE001 — a verdict, not a crash
                conn.rollback()
                return Verdict(database, False, str(exc).strip(), pending)
        conn.commit()
        return Verdict(database, True, "converged", pending, pending)
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
    spec: ClusterSpec,
    work_dir: Path,
    databases: Optional[Sequence[str]] = None,
) -> List[Verdict]:
    """Rehearse every tenant database on the connected cluster."""
    targets = list(databases) if databases is not None else tenant_databases(dsn_for)
    return [
        rehearse(dsn_for(name), database=name, spec=spec, work_dir=work_dir)
        for name in targets
    ]


__all__ = [
    "PLATFORM_DATABASE",
    "REHEARSAL_PREFIX",
    "Verdict",
    "rehearse",
    "rehearse_fleet",
    "tenant_databases",
]
