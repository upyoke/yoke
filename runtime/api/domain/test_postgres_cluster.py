"""Tests for the shared Postgres cluster-lifecycle core."""

from __future__ import annotations

import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

from yoke_core.domain import postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec


def _completed(stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def _spec(tmp_path: Path, **overrides) -> ClusterSpec:
    defaults = dict(root=tmp_path / "cluster", superuser="clusteruser")
    defaults.update(overrides)
    return ClusterSpec(**defaults)


def test_binary_resolution_path_vs_pinned_dir(tmp_path):
    from_path = _spec(tmp_path)
    pinned = _spec(tmp_path, bin_dir=tmp_path / "engine" / "bin")

    assert postgres_cluster.binary(from_path, "initdb") == "initdb"
    assert postgres_cluster.binary(pinned, "initdb") == str(
        tmp_path / "engine" / "bin" / "initdb"
    )


def test_dsn_targets_unix_socket_with_superuser(tmp_path):
    spec = _spec(tmp_path)
    assert postgres_cluster.dsn(spec) == (
        f"host={spec.sock_dir} user=clusteruser dbname=postgres"
    )
    assert postgres_cluster.dsn(spec, dbname="other").endswith("dbname=other")


def test_initdb_recovers_partial_nonempty_data_dir(monkeypatch, tmp_path):
    spec = _spec(tmp_path)
    partial_data = spec.data_dir
    partial_data.mkdir(parents=True)
    (partial_data / "leftover").write_text("partial init", encoding="utf-8")
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        assert not (partial_data / "leftover").exists()
        return _completed()

    monkeypatch.setattr(postgres_cluster, "_run", fake_run)

    assert postgres_cluster.initdb_if_needed(spec) == 0
    assert calls == [
        [
            "initdb",
            "-D",
            str(partial_data),
            "-U",
            "clusteruser",
            "--auth=trust",
            "--locale=C",
            "--encoding=UTF8",
        ]
    ]


def test_initdb_noop_when_cluster_exists(monkeypatch, tmp_path):
    spec = _spec(tmp_path)
    spec.data_dir.mkdir(parents=True)
    (spec.data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")
    monkeypatch.setattr(
        postgres_cluster,
        "_run",
        lambda argv, **kw: pytest.fail("initdb must not run on a live data dir"),
    )

    assert postgres_cluster.initdb_if_needed(spec) == 0


def test_server_options_render_socket_only_plus_settings(tmp_path):
    spec = _spec(
        tmp_path,
        server_settings=(("max_connections", "50"), ("fsync", "off")),
    )
    opts = postgres_cluster.server_options(spec)

    assert f"-k {spec.sock_dir}" in opts
    assert "-c listen_addresses=''" in opts
    assert "-c max_connections=50" in opts
    assert "-c fsync=off" in opts


def test_start_server_uses_pinned_binaries_and_options(monkeypatch, tmp_path):
    spec = _spec(tmp_path, bin_dir=tmp_path / "engine" / "bin")
    calls = []
    monkeypatch.setattr(
        postgres_cluster,
        "_run",
        lambda argv, **kw: calls.append(argv) or _completed(),
    )

    assert postgres_cluster.start_server(spec).returncode == 0
    argv = calls[0]
    assert argv[0] == str(tmp_path / "engine" / "bin" / "pg_ctl")
    assert argv[argv.index("-o") + 1] == postgres_cluster.server_options(spec)
    assert argv[-2:] == ["-w", "start"]


def test_stop_uses_spec_stop_mode(monkeypatch, tmp_path):
    spec = _spec(tmp_path, stop_mode="immediate")
    spec.data_dir.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(
        postgres_cluster,
        "_run",
        lambda argv, **kw: calls.append(argv) or _completed(),
    )

    assert postgres_cluster.stop(spec) == 0
    assert calls[0][calls[0].index("-m") + 1] == "immediate"


def test_ensure_started_skips_start_when_ready(monkeypatch, tmp_path):
    spec = _spec(tmp_path)
    calls = []
    monkeypatch.setattr(
        postgres_cluster,
        "initdb_if_needed",
        lambda s: calls.append("initdb") or 0,
    )
    monkeypatch.setattr(postgres_cluster, "is_ready", lambda s: True)
    monkeypatch.setattr(
        postgres_cluster,
        "start_server",
        lambda s: pytest.fail("must not start an already-ready cluster"),
    )

    assert postgres_cluster.ensure_started(spec) == 0
    assert calls == ["initdb"]
    assert spec.sock_dir.is_dir()
    assert stat.S_IMODE(spec.sock_dir.stat().st_mode) == 0o700


def test_ensure_started_rejects_symlink_socket_directory(tmp_path):
    target = tmp_path / "other-directory"
    target.mkdir()
    socket_dir = tmp_path / "cluster-socket"
    socket_dir.symlink_to(target, target_is_directory=True)
    spec = _spec(tmp_path, socket_dir=socket_dir)

    with pytest.raises(
        postgres_cluster.PostgresClusterError,
        match="not a private directory",
    ):
        postgres_cluster.ensure_started(spec)


@pytest.mark.skipif(
    shutil.which("initdb") is None,
    reason="system Postgres binaries not on PATH",
)
def test_live_lifecycle_on_scratch_root():
    """Real initdb/start/status/stop round-trip against a scratch root.

    The root is allocated directly under the OS temp dir, not pytest's
    ``tmp_path``: unix socket paths cap at ~103 bytes and the nested
    pytest tmp dir blows the limit on macOS.
    """
    scratch = Path(tempfile.mkdtemp(prefix="yoke-pgcore-", dir="/tmp"))
    spec = _spec(
        scratch,
        superuser="lifecycleuser",
        server_settings=(("fsync", "off"),),
        stop_mode="immediate",
    )
    try:
        assert postgres_cluster.ensure_started(spec) == 0
        assert postgres_cluster.is_ready(spec)
        # Idempotent re-entry: no error, still ready.
        assert postgres_cluster.ensure_started(spec) == 0
        probe = postgres_cluster.psql(spec, "SELECT 1")
        assert probe.returncode == 0
        assert probe.stdout.strip() == "1"
        assert postgres_cluster.stop(spec) == 0
        assert not postgres_cluster.is_ready(spec)
    finally:
        postgres_cluster.destroy(spec)
        shutil.rmtree(scratch, ignore_errors=True)
    assert not spec.root.exists()
