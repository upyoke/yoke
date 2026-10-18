"""Tests for the disposable local Postgres cluster frontend.

The initdb/pg_ctl choreography itself is covered by
``runtime/api/domain/test_postgres_cluster.py``; these tests pin the
disposable frontend's spec (binary resolution, throwaway tuning, scratch
root) and its ownership-gated orphan sweep.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import postgres_cluster
from yoke_core.tools import pg_testcluster


@pytest.fixture(autouse=True)
def _binary_environment(monkeypatch):
    monkeypatch.delenv("YOKE_PG_BIN_DIR", raising=False)


def _completed(stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def test_spec_uses_disposable_cluster_settings(monkeypatch):
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", "/tmp/yoke-pgtest-spec")
    monkeypatch.setattr(
        pg_testcluster.postgres_binaries, "installed_bin_dir", lambda: None
    )

    spec = pg_testcluster._spec()

    assert spec.superuser == pg_testcluster.PGUSER
    assert spec.bin_dir is None  # fallback to system binaries from PATH
    assert spec.socket_dir is None  # short root keeps the socket inside the cluster
    assert spec.stop_mode == "immediate"
    settings = dict(spec.server_settings)
    assert settings["max_connections"] == pg_testcluster.LOCAL_CLUSTER_MAX_CONNECTIONS
    assert settings["max_wal_size"] == "512MB"
    assert settings["fsync"] == "off"
    assert settings["full_page_writes"] == "off"

    opts = postgres_cluster.server_options(spec)
    assert f"-c max_connections={pg_testcluster.LOCAL_CLUSTER_MAX_CONNECTIONS}" in opts
    assert "-c fsync=off" in opts
    assert "-c listen_addresses=''" in opts


def test_ensure_started_recreates_on_stale_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", str(tmp_path / "cluster"))
    calls = []

    monkeypatch.setattr(
        postgres_cluster,
        "initdb_if_needed",
        lambda spec: calls.append("initdb") or 0,
    )
    monkeypatch.setattr(
        postgres_cluster,
        "ensure_started",
        lambda spec: calls.append("start") or 0,
    )
    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: True)
    monkeypatch.setattr(pg_testcluster, "_settings_match", lambda: False)
    monkeypatch.setattr(
        pg_testcluster,
        "destroy",
        lambda: calls.append("destroy") or 0,
    )

    assert pg_testcluster.ensure_started() == 0
    assert calls == ["initdb", "destroy", "initdb", "start"]


def test_env_block_exports_cluster_root_and_dsn(monkeypatch):
    root = "/tmp/yoke-pgtest-cluster-custom"
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", root)

    block = pg_testcluster.env_block()

    assert f"export YOKE_PG_CLUSTER_ROOT={root}" in block
    assert f"host={root}/sock user=yoketest dbname=postgres" in block


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


def test_spec_uses_installed_embedded_binaries_without_fetching(monkeypatch, tmp_path):
    binaries = tmp_path / "embedded" / "bin"
    monkeypatch.setattr(
        pg_testcluster.postgres_binaries, "installed_bin_dir", lambda: binaries
    )

    spec = pg_testcluster._spec()

    assert spec.bin_dir == binaries
    assert postgres_cluster.binary(spec, "initdb") == str(binaries / "initdb")


def test_spec_shortens_overlong_cluster_root(monkeypatch, tmp_path):
    root = tmp_path / ("nested-scratch-" * 8) / "yoke-pgtest-cluster"
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", str(root))

    spec = pg_testcluster._spec()
    socket_path = spec.sock_dir / f".s.PGSQL.{postgres_cluster.SOCKET_PORT}"

    assert spec.root == root
    assert spec.socket_dir is not None
    assert spec.sock_dir != root / "sock"
    assert len(os.fsencode(socket_path)) <= (
        postgres_cluster._MAX_POSTGRES_SOCKET_PATH_BYTES
    )


def test_long_root_starts_cluster_on_short_socket(monkeypatch):
    socket_name = f".s.PGSQL.{postgres_cluster.SOCKET_PORT}"
    root = Path("/tmp") / ("yoke-long-root-" + ("n" * 80))
    assert len(os.fsencode(root / "sock" / socket_name)) > (
        postgres_cluster._MAX_POSTGRES_SOCKET_PATH_BYTES
    )
    root.mkdir()
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", str(root))
    calls = []

    def fake_run(argv, **_kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(postgres_cluster, "_run", fake_run)
    try:
        assert pg_testcluster.ensure_started() == 0
        spec = pg_testcluster._spec()
        socket_path = spec.sock_dir / socket_name
        assert spec.socket_dir is not None
        assert len(os.fsencode(socket_path)) <= (
            postgres_cluster._MAX_POSTGRES_SOCKET_PATH_BYTES
        )
        assert stat.S_IMODE(spec.sock_dir.stat().st_mode) == 0o700
        start = [argv for argv in calls if argv[-1] == "start"]
        assert start
        assert str(spec.sock_dir) in start[0][start[0].index("-o") + 1]
    finally:
        pg_testcluster.destroy()


def test_env_block_exports_pinned_binaries_for_disposable_homes(monkeypatch):
    from pathlib import Path
    import shlex

    binaries = Path("/embedded engine/bin")
    monkeypatch.setattr(
        pg_testcluster.postgres_binaries, "installed_bin_dir", lambda: binaries
    )
    exports = [shlex.split(line)[1] for line in pg_testcluster.env_block().splitlines()]
    assert f"YOKE_PG_BIN_DIR={binaries}" in exports
