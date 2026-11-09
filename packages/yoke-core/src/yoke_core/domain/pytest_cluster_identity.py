"""Identity and observation of the shared disposable test cluster."""
from __future__ import annotations
import os
from pathlib import Path
from yoke_core.domain import postgres_binaries, postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec

PGUSER = "yoketest"



LOCAL_CLUSTER_MAX_CONNECTIONS = "800"



LOCAL_CLUSTER_MAX_WAL_SIZE = "512MB"



LOCAL_CLUSTER_MIN_WAL_SIZE = "80MB"



DISPOSABLE_SERVER_SETTINGS: tuple = (
    ("max_connections", LOCAL_CLUSTER_MAX_CONNECTIONS),
    ("max_wal_size", LOCAL_CLUSTER_MAX_WAL_SIZE),
    ("min_wal_size", LOCAL_CLUSTER_MIN_WAL_SIZE),
    ("timezone", "Asia/Kathmandu"),
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
    root = _root()
    return ClusterSpec(
        root=root,
        superuser=PGUSER,
        server_settings=DISPOSABLE_SERVER_SETTINGS,
        bin_dir=postgres_binaries.pinned_bin_dir(),
        stop_mode="immediate",  # throwaway data: skip the shutdown checkpoint
        socket_dir=postgres_cluster.socket_dir_for_root(root),
    )



def dsn() -> str:
    """Base maintenance DSN (database ``postgres``) for the running cluster."""
    return postgres_cluster.dsn(_spec())



def _is_ready() -> bool:
    return postgres_cluster.is_ready(_spec())

