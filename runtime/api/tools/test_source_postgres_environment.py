"""Test resource sharing survives disposable settings and evidence lifetimes."""

import json
import os
from pathlib import Path
import signal

import pytest

from yoke_cli.config import local_universe_setup
from yoke_core.domain import qa_case_command_stream
from yoke_core.tools import pg_testcluster
from yoke_core.tools import pg_testcluster_reclaim as reclaim
from yoke_core.tools import source_machine_home
from yoke_core.tools.source_postgres_environment import shared_postgres_environment


def test_repeated_source_homes_keep_cluster_and_binary_identity(tmp_path, monkeypatch):
    machine = tmp_path / "machine"
    machine.mkdir()
    binaries = machine / "postgres/17.10.0/bin"
    binaries.mkdir(parents=True)
    (binaries / "initdb").touch()
    (machine / "config.json").write_text(
        json.dumps({"temp_root": str(tmp_path / "scratch")})
    )
    env = {"YOKE_MACHINE_HOME": str(machine), "YOKE_SESSION_ID": "fixture"}
    identities = []
    for _ in range(2):
        with source_machine_home.isolated_machine_home(env) as child:
            identities.append((child["YOKE_PG_CLUSTER_ROOT"], child["YOKE_PG_BIN_DIR"]))
            assert not Path(child["YOKE_PG_CLUSTER_ROOT"]).is_relative_to(
                child["YOKE_SCRATCH_ROOT"]
            )
    assert identities[0] == identities[1]
    assert identities[0][0] == str(tmp_path / "scratch/yoke-pgtest-cluster")
    assert identities[0][1] == str(machine / "postgres/17.10.0/bin")


def test_qa_environment_preserves_cluster_when_home_is_replaced(tmp_path, monkeypatch):
    selected = tmp_path / "chosen-cluster"
    binaries = tmp_path / ".yoke/postgres/17.10.0/bin"
    binaries.mkdir(parents=True)
    (binaries / "initdb").touch()
    import sys
    from yoke_core.domain import qa_case_candidate_source as candidate
    from yoke_core.domain.source_python_environment import SourcePythonEnvironment

    monkeypatch.setattr(candidate.source, "is_yoke_shaped_tree", lambda root: True)
    monkeypatch.setattr(
        candidate.source, "with_source_pythonpath", lambda env, root: dict(env)
    )
    monkeypatch.setattr(candidate.source, "import_origins", lambda *a, **kw: ({}, None))
    monkeypatch.setattr(
        candidate.source_python_environment,
        "resolve",
        lambda root, env: SourcePythonEnvironment(
            sys.executable, dict(env), {"declaration": {}}
        ),
    )
    incoming = qa_case_command_stream.product_command_environment(
        {"HOME": str(tmp_path), "YOKE_PG_CLUSTER_ROOT": str(selected)}
    )
    with candidate.candidate_source(tmp_path, incoming) as binding:
        env = dict(binding.env)
    env.update(HOME="/disposable", YOKE_MACHINE_HOME="/disposable/.yoke")
    assert shared_postgres_environment(env)["YOKE_PG_CLUSTER_ROOT"] == str(selected)
    assert env["YOKE_PG_BIN_DIR"] == str(tmp_path / ".yoke/postgres/17.10.0/bin")


def test_disposable_cluster_uses_pinned_binaries(tmp_path, monkeypatch, capsys):
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "initdb").touch()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("YOKE_PG_BIN_DIR", str(binary))
    assert pg_testcluster._spec().bin_dir == binary
    (binary / "initdb").unlink()
    assert pg_testcluster.ensure_started() == 1
    error = capsys.readouterr().err
    assert "postgres_binaries_unavailable" in error
    assert "install embedded binaries" in error


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_evidence_cleanup_on_interrupt(tmp_path, monkeypatch, interruption):
    visited = []
    monkeypatch.setattr(reclaim, "destroy_evidence_clusters", visited.append)
    env = {"YOKE_MACHINE_HOME": str(tmp_path), "YOKE_SESSION_ID": "fixture"}
    with pytest.raises(interruption):
        with source_machine_home.isolated_machine_home(env) as child:
            evidence = Path(child["YOKE_SCRATCH_ROOT"])
            raise interruption()
    assert visited == [evidence]
    assert not evidence.exists()


def test_sigterm_unwinds_and_restores_handler(tmp_path, monkeypatch):
    visited = []
    monkeypatch.setattr(reclaim, "destroy_evidence_clusters", visited.append)
    previous = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as ended:
        with source_machine_home.isolated_machine_home(
            {"YOKE_MACHINE_HOME": str(tmp_path), "YOKE_SESSION_ID": "fixture"}
        ):
            os.kill(os.getpid(), signal.SIGTERM)
    assert ended.value.code == 143
    assert len(visited) == 1
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.parametrize("root", ["/private-test-cluster", ""])
@pytest.mark.parametrize(
    "operation",
    [local_universe_setup.postgres_start, local_universe_setup.postgres_stop],
)
def test_local_postgres_refuses_test_root_before_loading_engine(
    monkeypatch, operation, root
):
    monkeypatch.setenv("YOKE_PG_CLUSTER_ROOT", root)
    monkeypatch.setattr(
        local_universe_setup, "_engine", lambda: pytest.fail("touched local universe")
    )
    with pytest.raises(
        local_universe_setup.LocalUniverseSetupError,
        match="local_postgres_test_cluster_override.*unset",
    ):
        operation()


def test_prune_preserves_shared_young_and_connected_clusters(tmp_path, monkeypatch):
    roots = [
        tmp_path / name / "yoke-pgtest-cluster"
        for name in ("shared", "young", "busy", "orphan")
    ]
    monkeypatch.setattr(
        reclaim,
        "_postmasters",
        lambda: [(i, root, tmp_path) for i, root in enumerate(roots)],
    )
    monkeypatch.setattr(
        reclaim,
        "_spec",
        lambda pid, root, bins: (
            reclaim.ClusterSpec(root, "yoketest"),
            reclaim.time.time() if pid == 1 else 0,
        ),
    )
    monkeypatch.setattr(reclaim, "_idle", lambda spec: spec.root != roots[2])
    destroyed = []
    monkeypatch.setattr(
        reclaim, "_destroy", lambda pid, spec: destroyed.append(spec.root)
    )
    assert reclaim.prune_clusters(roots[0]) == 0
    assert destroyed == [roots[3]]


def test_cleanup_reclaims_only_its_own_evidence_cluster(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    inside = evidence / "yoke-pgtest-cluster"
    outside = tmp_path / "other/yoke-pgtest-cluster"
    (inside / "data").mkdir(parents=True)
    (inside / "data/PG_VERSION").write_text("17")
    (inside / "data/postmaster.pid").write_text("1")
    monkeypatch.setattr(
        reclaim, "_postmasters", lambda: [(1, inside, tmp_path), (2, outside, tmp_path)]
    )
    monkeypatch.setattr(
        reclaim,
        "_spec",
        lambda pid, root, bins: (reclaim.ClusterSpec(root, "yoketest"), 0),
    )
    destroyed = []

    def destroy(pid, spec):
        destroyed.append(spec.root)
        reclaim.shutil.rmtree(spec.root)

    monkeypatch.setattr(reclaim, "_destroy", destroy)
    reclaim.destroy_evidence_clusters(evidence)
    assert destroyed == [inside]


def test_failed_stop_never_removes_live_data(tmp_path, monkeypatch):
    root = tmp_path / "yoke-pgtest-cluster"
    data = root / "data"
    data.mkdir(parents=True)
    marker = data / "postmaster.pid"
    marker.write_text(f"42\n{data}\n0\n5432\n{root / 'sock'}\n")
    monkeypatch.setattr(
        reclaim.postgres_cluster,
        "_run",
        lambda *args, **kwargs: reclaim.subprocess.CompletedProcess(
            [], 1, "", "still live"
        ),
    )
    with pytest.raises(OSError, match="stop failed"):
        reclaim._destroy(42, reclaim.ClusterSpec(root, "yoketest", bin_dir=tmp_path))
    assert marker.exists()


def test_postmaster_inventory_excludes_foreign_users_and_background_workers(
    monkeypatch,
):
    listing = f"{os.getuid()} 12 /pg/bin/postgres -D /tmp/old/yoke-pgtest-cluster/data\n{os.getuid()} 13 /pg/bin/postgres -D /home/local-universe/data\n{os.getuid() + 1} 14 /pg/bin/postgres -D /tmp/foreign/yoke-pgtest-cluster/data\n{os.getuid()} 15 postgres: checkpointer\n"
    monkeypatch.setattr(
        reclaim.subprocess,
        "run",
        lambda *args, **kwargs: reclaim.subprocess.CompletedProcess([], 0, listing, ""),
    )
    assert reclaim._postmasters() == [
        (12, Path("/tmp/old/yoke-pgtest-cluster"), Path("/pg/bin")),
        (13, Path("/home/local-universe"), Path("/pg/bin")),
    ]


@pytest.mark.parametrize("name", ["yoke-pgtest-cluster", "custom-cluster", ""])
def test_evidence_cleanup_removes_stopped_cluster_data(tmp_path, monkeypatch, name):
    monkeypatch.setattr(reclaim, "_postmasters", lambda: [])
    data = tmp_path / name / "data"
    data.mkdir(parents=True)
    (data / "PG_VERSION").write_text("17")
    reclaim.destroy_evidence_clusters(tmp_path)
    assert not data.exists()
    assert tmp_path.exists()


def test_missing_embedded_cache_remains_pinned_in_disposable_home(tmp_path):
    env = shared_postgres_environment({"YOKE_MACHINE_HOME": str(tmp_path)})
    assert env["YOKE_PG_BIN_DIR"] == str(tmp_path / "postgres/17.10.0/bin")


def test_prune_does_not_touch_durable_cluster_names(tmp_path, monkeypatch):
    monkeypatch.setattr(
        reclaim, "_postmasters", lambda: [(1, tmp_path / "local-universe", tmp_path)]
    )
    monkeypatch.setattr(
        reclaim, "_spec", lambda *args: pytest.fail("inspected durable cluster")
    )
    assert reclaim.prune_clusters(tmp_path / "shared") == 0


def test_empty_evidence_never_inspects_processes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        reclaim, "_postmasters", lambda: pytest.fail("no cluster needs inspection")
    )
    reclaim.destroy_evidence_clusters(tmp_path)


def test_unknown_postmaster_identity_refuses_instead_of_leaking_silently(
    tmp_path, monkeypatch
):
    data = tmp_path / "custom/data"
    data.mkdir(parents=True)
    (data / "PG_VERSION").write_text("17")
    (data / "postmaster.pid").write_text("unknown")
    monkeypatch.setattr(reclaim, "_postmasters", lambda: [])
    with pytest.raises(OSError, match="pgtest_evidence_cleanup_failed"):
        reclaim.destroy_evidence_clusters(tmp_path)
    assert data.exists()


def test_postmaster_inventory_preserves_spaces_in_owned_paths(monkeypatch):
    listing = f"{os.getuid()} 12 /embedded engine/bin/postgres -D /tmp/evidence/private cluster/data -k /tmp/socket -p 5432\n"
    monkeypatch.setattr(
        reclaim.subprocess,
        "run",
        lambda *a, **kw: reclaim.subprocess.CompletedProcess([], 0, listing, ""),
    )
    assert reclaim._postmasters() == [
        (12, Path("/tmp/evidence/private cluster"), Path("/embedded engine/bin"))
    ]


def test_ordinary_command_qa_does_not_inject_test_cluster_resources(tmp_path):
    env = qa_case_command_stream.product_command_environment(
        {"HOME": str(tmp_path), "PATH": "/system/bin"}
    )
    assert "YOKE_PG_CLUSTER_ROOT" not in env
    assert "YOKE_PG_BIN_DIR" not in env


def test_prune_refuses_an_older_source_runner_without_shared_root(monkeypatch, capsys):
    from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV

    monkeypatch.setenv(SOURCE_DEV_RUN_ROOT_ENV, "/claimed-source")
    monkeypatch.delenv("YOKE_PG_CLUSTER_ROOT", raising=False)
    monkeypatch.setattr(
        pg_testcluster, "_root", lambda: pytest.fail("ambiguous shared root")
    )
    assert pg_testcluster.prune_clusters() == 1
    assert "pgtest_shared_root_unbound" in capsys.readouterr().err
