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
    python3 -m yoke_core.tools.pg_testcluster prune      # drop stale test DBs
    python3 -m yoke_core.tools.pg_testcluster stop       # stop server, keep data dir
    python3 -m yoke_core.tools.pg_testcluster destroy    # stop + remove data dir

Typical local proof flow::

    eval "$(python3 -m yoke_core.tools.pg_testcluster start)"
    yoke watch pytest -- runtime/api/
    python3 -m yoke_core.tools.pg_testcluster destroy
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from yoke_core.domain import postgres_cluster
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


def _psql(sql: str):
    return postgres_cluster.psql(_spec(), sql)


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


# Concurrent local runs on one cluster are supported by design (each worker
# gets a uniquely named ambient database). A run that has just created a
# database but not yet connected to it looks idle, so "no active connection"
# alone would let one run reclaim another's database. Requiring the database
# to ALSO be untouched for this long closes that window: a live run writes to
# its databases continuously, while a database orphaned by an interrupted run
# goes quiet the moment that run dies. Erring long is free — anything missed
# is reclaimed by the next run.
STALE_TEST_DB_QUIET_MINUTES = 15


def prune_stale_test_databases() -> int:
    """Drop leaked Yoke test databases left by prior interrupted runs.

    Reclaims only databases that are both unconnected AND quiet for
    :data:`STALE_TEST_DB_QUIET_MINUTES`, so a concurrently running suite keeps
    its own databases. When the age signal cannot be read the prune declines
    rather than falling back to the connection check alone — deleting another
    run's database is far worse than leaving garbage for the next run.
    """
    if not _is_ready():
        return 0
    res = _psql(
        "SELECT datname FROM pg_database d "
        "WHERE datname LIKE 'yoke_test%' "
        "AND datname NOT IN ("
        "  SELECT datname FROM pg_stat_activity WHERE datname IS NOT NULL"
        ") "
        "AND (pg_stat_file('base/' || d.oid::text, true)).modification "
        f"  < now() - interval '{STALE_TEST_DB_QUIET_MINUTES} minutes' "
        "ORDER BY datname"
    )
    if res.returncode != 0:
        # Most likely the cluster role cannot read server files. Decline the
        # prune loudly instead of pruning on the connection check alone.
        sys.stderr.write(res.stdout + res.stderr)
        sys.stderr.write(
            "pg_testcluster: cannot determine test-database age; skipping "
            "prune rather than risk reclaiming a concurrent run's database\n"
        )
        return 0
    reclaimed = 0
    for name in [line for line in res.stdout.splitlines() if line]:
        if not name.startswith("yoke_test"):
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        drop = _psql(f"DROP DATABASE IF EXISTS {quoted}")
        if drop.returncode != 0:
            sys.stderr.write(drop.stdout + drop.stderr)
            return drop.returncode
        reclaimed += 1
    # Say so when there was anything to reclaim. A silent prune let this
    # cluster reach 275 leaked databases and 12G unnoticed, because the only
    # visible symptom was a suite that got slower and slower.
    if reclaimed:
        sys.stderr.write(
            f"pg_testcluster: reclaimed {reclaimed} leaked test database(s) "
            f"from interrupted runs\n"
        )
    return 0


def prepare_for_pytest() -> int:
    """Start the local cluster and prune leaked DBs before a pytest run."""
    rc = ensure_started()
    if rc != 0:
        return rc
    return prune_stale_test_databases()


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
        "prune": prune_stale_test_databases,
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
