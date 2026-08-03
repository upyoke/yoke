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

from yoke_core.domain import postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec

PGUSER = "yoketest"
# Sized so a burst of concurrent gate invocations that slips past admission
# control degrades to slow instead of hard "too many clients" failures:
# measured ~11 connections per full gate, so 200 died at ~18 gates.
LOCAL_CLUSTER_MAX_CONNECTIONS = "800"
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


def start_detached_orphan_sweep() -> None:
    """Kick off the detached orphan sweep (see the orphans module)."""
    from yoke_core.tools import pg_testcluster_orphans

    pg_testcluster_orphans.start_detached_orphan_sweep()


def sweep_orphaned_test_databases() -> int:
    """Reclaim orphaned test databases (see the orphans module)."""
    from yoke_core.tools import pg_testcluster_orphans

    return pg_testcluster_orphans.sweep_orphaned_test_databases()


def prepare_for_pytest() -> int:
    """Start the local cluster, then let a detached sweep reclaim orphans.

    The sweep is ownership-gated — it can only ever touch databases whose
    owning invocation has already exited — so it is safe to run alongside
    suites already in flight, and detaching it keeps it off their startup path.
    """
    rc = ensure_started()
    if rc != 0:
        return rc
    start_detached_orphan_sweep()
    return 0


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
