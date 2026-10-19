"""Real postmasters prove exit cleanup and idle-cluster pruning."""

import os
from pathlib import Path
import shutil
import tempfile

import pytest

from yoke_core.domain import postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec
from yoke_core.tools import pg_testcluster
from yoke_core.tools import pg_testcluster_reclaim as reclaim
from yoke_core.tools.source_machine_home import isolated_machine_home

pytestmark = pytest.mark.skipif(
    shutil.which("initdb") is None,
    reason="PostgreSQL binaries are required for real postmaster lifetime proof",
)


def _spec(root):
    return ClusterSpec(
        root=root,
        superuser="yoketest",
        bin_dir=pg_testcluster.bin_dir(),
        server_settings=(("fsync", "off"),),
        stop_mode="immediate",
    )


@pytest.mark.parametrize(
    "name",
    ["yoke-pgtest-cluster", "private-cluster", pytest.param("", id="evidence-root")],
)
def test_interrupt_destroys_real_evidence_postmaster(tmp_path, name):
    env = {
        **os.environ,
        "YOKE_MACHINE_HOME": str(tmp_path),
        "YOKE_SESSION_ID": "fixture",
    }
    root = None
    try:
        with pytest.raises(KeyboardInterrupt):
            with isolated_machine_home(env) as child:
                evidence = Path(child["YOKE_SCRATCH_ROOT"])
                capture = evidence / "proof.log"
                capture.write_text("retained proof")
                root = evidence / name
                spec = _spec(root)
                assert postgres_cluster.ensure_started(spec) == 0
                assert postgres_cluster.is_ready(spec)
                raise KeyboardInterrupt()
        assert not spec.data_dir.exists()
        assert capture.read_text() == "retained proof"
        if name:
            assert not root.exists()
        assert not postgres_cluster.is_ready(spec)
    finally:
        if root is not None:
            if spec.data_dir.exists():
                postgres_cluster.destroy(spec)
            shutil.rmtree(evidence, ignore_errors=True)


def test_real_prune_keeps_clients_then_reaps_idle_orphan(monkeypatch):
    import psycopg

    evidence = Path(tempfile.mkdtemp(prefix="yoke-prune-proof-", dir="/tmp"))
    spec = _spec(evidence / "yoke-pgtest-cluster")
    try:
        assert postgres_cluster.ensure_started(spec) == 0
        owned = [
            row
            for row in reclaim._postmasters()
            if row[1].resolve() == spec.root.resolve()
        ]
        assert len(owned) == 1
        monkeypatch.setattr(reclaim, "_postmasters", lambda: owned)
        monkeypatch.setattr(reclaim, "MIN_IDLE_AGE_SECONDS", 0)
        with psycopg.connect(postgres_cluster.dsn(spec)):
            assert reclaim.prune_clusters(evidence / "shared") == 0
            assert postgres_cluster.is_ready(spec)
        assert reclaim.prune_clusters(evidence / "shared") == 0
        assert not spec.root.exists()
        assert not postgres_cluster.is_ready(spec)
    finally:
        if spec.root.exists():
            postgres_cluster.destroy(spec)
        evidence.rmdir()
