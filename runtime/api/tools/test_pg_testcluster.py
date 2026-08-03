"""Tests for the disposable local Postgres cluster frontend.

The initdb/pg_ctl choreography itself is covered by
``runtime/api/domain/test_postgres_cluster.py``; these tests pin the
disposable frontend's spec (system binaries, throwaway tuning, scratch
root) and its ownership-gated orphan sweep.
"""

from __future__ import annotations

import subprocess

from yoke_core.domain import postgres_cluster
from yoke_core.tools import pg_testcluster


def _completed(stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def test_spec_uses_disposable_cluster_settings(monkeypatch):
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", "/tmp/yoke-pgtest-spec")

    spec = pg_testcluster._spec()

    assert spec.superuser == pg_testcluster.PGUSER
    assert spec.bin_dir is None  # system binaries from PATH
    assert spec.stop_mode == "immediate"
    settings = dict(spec.server_settings)
    assert (
        settings["max_connections"]
        == pg_testcluster.LOCAL_CLUSTER_MAX_CONNECTIONS
    )
    assert settings["max_wal_size"] == "512MB"
    assert settings["fsync"] == "off"
    assert settings["full_page_writes"] == "off"

    opts = postgres_cluster.server_options(spec)
    assert (
        f"-c max_connections={pg_testcluster.LOCAL_CLUSTER_MAX_CONNECTIONS}"
        in opts
    )
    assert "-c fsync=off" in opts
    assert "-c listen_addresses=''" in opts


def test_ensure_started_recreates_on_stale_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", str(tmp_path / "cluster"))
    calls = []

    monkeypatch.setattr(
        postgres_cluster, "initdb_if_needed",
        lambda spec: calls.append("initdb") or 0,
    )
    monkeypatch.setattr(
        postgres_cluster, "ensure_started",
        lambda spec: calls.append("start") or 0,
    )
    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: True)
    monkeypatch.setattr(pg_testcluster, "_settings_match", lambda: False)
    monkeypatch.setattr(
        pg_testcluster, "destroy", lambda: calls.append("destroy") or 0,
    )

    assert pg_testcluster.ensure_started() == 0
    assert calls == ["initdb", "destroy", "initdb", "start"]



def test_env_block_exports_cluster_root_and_dsn(monkeypatch):
    root = "/tmp/yoke-pgtest-cluster-custom"
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", root)

    block = pg_testcluster.env_block()

    assert f'export YOKE_PG_CLUSTER_ROOT="{root}"' in block
    assert f'host={root}/sock user=yoketest dbname=postgres' in block


def test_root_without_override_resolves_under_global_scratch_root(
    monkeypatch, tmp_path
):
    """Without YOKE_PG_CLUSTER_ROOT the cluster lives under the shared
    project-agnostic scratch root — ONE location across all execution contexts,
    not a per-context $TMPDIR guess (the source of cross-context divergence)."""
    from yoke_core.domain import project_scratch_dir

    monkeypatch.delenv("YOKE_PG_CLUSTER_ROOT", raising=False)
    monkeypatch.setattr(
        project_scratch_dir, "global_scratch_root", lambda: tmp_path / "scratch"
    )

    assert pg_testcluster._root() == tmp_path / "scratch" / "yoke-pgtest-cluster"
