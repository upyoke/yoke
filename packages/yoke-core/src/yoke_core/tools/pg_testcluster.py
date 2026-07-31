"""Disposable local PostgreSQL cluster for Yoke tests.

Frontend of the shared cluster-lifecycle core
(:mod:`yoke_core.domain.postgres_cluster`): system binaries from ``PATH``,
a throwaway data directory under the shared scratch root, and durability
turned off. This is the *local* equivalent of CI's GitHub Actions
``postgres`` service — it lets a developer run the suite against Postgres
without a system Postgres install touching any real database. The durable
sibling frontend is :mod:`yoke_core.domain.local_universe`.

The cluster is fully disposable: ``destroy`` stops it and removes the data
directory. ``start`` is idempotent (re-uses an existing data dir, no-ops if the
server is already accepting connections).

Subcommands::

    python3 -m yoke_core.tools.pg_testcluster start     # initdb + start; prints exports
    python3 -m yoke_core.tools.pg_testcluster env       # prints exports for a running cluster
    python3 -m yoke_core.tools.pg_testcluster status
    python3 -m yoke_core.tools.pg_testcluster prune      # reclaim orphaned test DBs
    python3 -m yoke_core.tools.pg_testcluster stop       # stop server, keep data dir
    python3 -m yoke_core.tools.pg_testcluster destroy    # stop + remove data dir

One cluster serves every concurrent invocation on the machine. Isolation
comes from owner-tagged database names
(:mod:`yoke_core.domain.pg_test_db_namespace`), not from a cluster per run:
a suite may only drop its own databases, and reclaiming what an interrupted
run left behind is this module's orphan sweep, gated on the owning process
having exited. ``YOKE_PG_CLUSTER_ROOT`` remains available for the rarer case
of wanting a wholly private cluster.

Typical local proof flow::

    eval "$(python3 -m yoke_core.tools.pg_testcluster start)"
    yoke watch pytest -- runtime/api/
    python3 -m yoke_core.tools.pg_testcluster destroy
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from yoke_core.domain import pg_test_db_namespace, postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec

PGUSER = "yoketest"
LOCAL_CLUSTER_MAX_CONNECTIONS = "200"
LOCAL_CLUSTER_MAX_WAL_SIZE = "512MB"
LOCAL_CLUSTER_MIN_WAL_SIZE = "80MB"

#: Throwaway-cluster server settings: high connection headroom for xdist
#: plus durability off — the data is disposable by definition.
DISPOSABLE_SERVER_SETTINGS: tuple = (
    ("max_connections", LOCAL_CLUSTER_MAX_CONNECTIONS),
    ("max_wal_size", LOCAL_CLUSTER_MAX_WAL_SIZE),
    ("min_wal_size", LOCAL_CLUSTER_MIN_WAL_SIZE),
    ("fsync", "off"),
    ("synchronous_commit", "off"),
    ("full_page_writes", "off"),
)


def _root() -> Path:
    # Shared across all projects + execution contexts. Resolves via the Yoke
    # scratch authority's project-agnostic global root so every context —
    # interactive shell, harness Bash tool, Codex, CI — agrees on ONE cluster
    # path instead of each guessing from its own ambient TMPDIR (the source of
    # cross-context cluster divergence). YOKE_PG_CLUSTER_ROOT overrides (e.g.
    # CI provides its own path).
    override = os.environ.get("YOKE_PG_CLUSTER_ROOT")
    if override:
        return Path(override)
    from yoke_core.domain.project_scratch_dir import global_scratch_root

    return global_scratch_root() / "yoke-pgtest-cluster"


def _spec() -> ClusterSpec:
    return ClusterSpec(
        root=_root(),
        superuser=PGUSER,
        server_settings=DISPOSABLE_SERVER_SETTINGS,
        bin_dir=None,  # system binaries from PATH
        stop_mode="immediate",  # throwaway data: skip the shutdown checkpoint
    )


def dsn() -> str:
    """Base maintenance DSN (database ``postgres``) for the running cluster."""
    return postgres_cluster.dsn(_spec())


def _psql(sql: str, *, statement_timeout_ms: int | None = None):
    return postgres_cluster.psql(
        _spec(), sql, statement_timeout_ms=statement_timeout_ms
    )


def _is_ready() -> bool:
    return postgres_cluster.is_ready(_spec())


def _show_setting(name: str) -> str | None:
    try:
        res = _psql(f"SHOW {name}")
    except FileNotFoundError:
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def _settings_match() -> bool:
    max_connections = _show_setting("max_connections")
    if max_connections is None:
        return True
    try:
        return int(max_connections) >= int(LOCAL_CLUSTER_MAX_CONNECTIONS)
    except ValueError:
        return True


def ensure_started() -> int:
    """Start the disposable cluster if needed without printing shell exports.

    A running cluster whose settings predate the current disposable tuning
    (e.g. too few connections for xdist) is destroyed and recreated — the
    data is throwaway, so recreate is the cheapest upgrade path.
    """
    spec = _spec()
    spec.sock_dir.mkdir(parents=True, exist_ok=True)
    rc = postgres_cluster.initdb_if_needed(spec)
    if rc != 0:
        return rc
    if _is_ready() and not _settings_match():
        destroy()
        rc = postgres_cluster.initdb_if_needed(spec)
        if rc != 0:
            return rc
    return postgres_cluster.ensure_started(spec)


# A database is reclaimable only once its owning invocation is gone, and the
# owner check alone would be unsafe: operating systems recycle PIDs, so a dead
# owner's PID can be reused by an unrelated live process. Requiring the
# database to ALSO be older than this makes a misread PID harmless. Erring
# long is free: anything missed is reclaimed by the next sweep.
ORPHAN_TEST_DB_MIN_AGE_MINUTES = 15

#: Age is read from ``PG_VERSION``, which PostgreSQL writes once when it
#: creates a database and never rewrites, so it is a true creation timestamp.
#: The database DIRECTORY's timestamp is not: the checkpointer and autovacuum
#: touch it for their own reasons, so an abandoned database keeps looking
#: freshly used and never becomes eligible. Measured against this cluster, the
#: directory signal made 0 of 161 known-dead databases reclaimable while the
#: creation signal correctly identified 138 — which is how a cluster silently
#: reaches hundreds of leaked databases and gigabytes of disk.
_DATABASE_CREATION_STAMP = "'base/' || d.oid::text || '/PG_VERSION'"

#: A drop that cannot take its lock promptly is a wedged database, not a slow
#: one. Failing fast keeps the sweep from parking on a lock and turning a
#: cleanup pass into the stall it exists to prevent.
ORPHAN_DROP_STATEMENT_TIMEOUT_MS = 5_000


def _owner_process_is_alive(pid: int) -> bool:
    """Return true when *pid* names a live process.

    ``PermissionError`` means the process exists but belongs to another user —
    still alive, and still not ours to reclaim.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True  # Unreadable means "assume live"; the sweep is optional.
    return True


def sweep_orphaned_test_databases() -> int:
    """Reclaim owner-tagged test databases whose owning invocation is gone.

    Every database an invocation creates carries that invocation's run tag, so
    the sweep can ask the operating system a definite question — is the owner
    still running? — instead of guessing from connection counts and mtimes.
    Databases belonging to live invocations are never touched, which is what
    makes this safe to run while other suites are mid-flight.

    Databases whose names carry no run tag are outside the namespace entirely
    (an operator's migration validation database, for instance) and are never
    candidates. Individual drop failures are reported and skipped rather than
    aborting the sweep: cleanup is best-effort, and a concurrent sweep that
    already reclaimed the same database must not fail this one.
    """
    if not _is_ready():
        return 0
    res = _psql(
        "SELECT datname FROM pg_database d "
        f"WHERE datname LIKE '{pg_test_db_namespace.OWNED_DATABASE_LIKE_PATTERN}' "
        f"AND (pg_stat_file({_DATABASE_CREATION_STAMP}, true)).modification "
        f"  < now() - interval '{ORPHAN_TEST_DB_MIN_AGE_MINUTES} minutes' "
        "ORDER BY datname"
    )
    if res.returncode != 0:
        # Most likely the cluster role cannot read server files. Decline the
        # sweep loudly rather than reclaiming on the PID check alone.
        sys.stderr.write(res.stdout + res.stderr)
        sys.stderr.write(
            "pg_testcluster: cannot determine test-database age; skipping "
            "orphan sweep rather than risk reclaiming a live run's database\n"
        )
        return 0
    reclaimed = 0
    for name in [line for line in res.stdout.splitlines() if line]:
        owner_pid = pg_test_db_namespace.owner_pid_of(name)
        if owner_pid is None or _owner_process_is_alive(owner_pid):
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        # FORCE terminates whatever the dead owner left connected — a leaked
        # child process is exactly how a database outlives its invocation.
        drop = _psql(
            f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)",
            statement_timeout_ms=ORPHAN_DROP_STATEMENT_TIMEOUT_MS,
        )
        if drop.returncode != 0:
            sys.stderr.write(drop.stdout + drop.stderr)
            continue
        reclaimed += 1
    # Say so when there was anything to reclaim. A silent sweep let this
    # cluster reach 275 leaked databases and 12G unnoticed, because the only
    # visible symptom was a suite that got slower and slower.
    if reclaimed:
        sys.stderr.write(
            f"pg_testcluster: reclaimed {reclaimed} orphaned test database(s) "
            f"from interrupted runs\n"
        )
    return 0


def prepare_for_pytest() -> int:
    """Start the local cluster and reclaim orphans before a pytest run.

    The sweep runs here rather than inside the suite because it is bounded and
    ownership-gated: it can only ever touch databases whose owning invocation
    has already exited, so a run starting up never contends with a run already
    in flight.
    """
    rc = ensure_started()
    if rc != 0:
        return rc
    return sweep_orphaned_test_databases()


def start() -> int:
    rc = prepare_for_pytest()
    if rc != 0:
        return rc
    print(env_block())
    return 0


def stop() -> int:
    return postgres_cluster.stop(_spec())


def destroy() -> int:
    return postgres_cluster.destroy(_spec())


def env_block() -> str:
    return "\n".join(
        [
            f'export YOKE_PG_CLUSTER_ROOT="{_root()}"',
            f'export YOKE_PG_DSN="{dsn()}"',
        ]
    )


def status() -> int:
    ready = _is_ready()
    print(f"cluster_root={_root()}")
    print(f"ready={ready}")
    return 0 if ready else 1


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    cmd = args[0] if args else "status"
    dispatch = {
        "start": start, "stop": stop, "destroy": destroy,
        "prune": sweep_orphaned_test_databases,
        "prepare": prepare_for_pytest,
        "status": status, "env": lambda: (print(env_block()) or 0),
    }
    handler = dispatch.get(cmd)
    if handler is None:
        sys.stderr.write(f"unknown subcommand {cmd!r}\n")
        return 2
    return handler()


if __name__ == "__main__":
    raise SystemExit(main())
