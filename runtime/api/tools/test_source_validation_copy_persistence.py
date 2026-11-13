"""Provision through admin exec and source isolation, then read it in a new run."""

from pathlib import Path
import sys
from types import SimpleNamespace

import psycopg

from uuid import uuid4

from runtime.api.domain.migration_copy_lifetime_support import (
    copy_cluster as _copy_cluster,  # noqa: F401 -- registers copy_cluster
)
from yoke_cli.config import db_admin_dsn_exec
from yoke_core.domain import connected_env_tunnel_coordination as coordination
from yoke_core.domain import connected_env_readiness_connector as connector
from yoke_core.domain import migration_validation_binding as binding
from yoke_core.domain import migration_fleet_preflight_transfer as transfer
from yoke_core.domain import pg_test_db_namespace, postgres_cluster
from yoke_core.domain.source_python_environment import SourcePythonEnvironment
from yoke_core.domain import source_pythonpath as _source_pythonpath
from yoke_core.tools import source_dev_run


def test_provisioned_copy_and_binding_survive_the_source_process(
    monkeypatch, tmp_path, capfd, copy_cluster
):
    authority_name = pg_test_db_namespace.database_name(uuid4().hex[:16])
    transfer.create_copy(copy_cluster, authority_name)
    validation_name = authority_name + binding.DERIVED_DATABASE_SUFFIX
    authority_dsn = postgres_cluster.dsn(copy_cluster, authority_name)
    monkeypatch.setenv("YOKE_PG_BIN_DIR", str(copy_cluster.bin_dir))
    home = tmp_path / "machine"
    home.mkdir()
    config = home / "config.json"
    config.write_text("{}")
    secret = home / "secrets" / "unrelated.token"
    secret.parent.mkdir()
    secret.write_text("unchanged-secret")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv(binding.YOKE_VALIDATION_DSN_ENV, raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    root = _source_pythonpath.repo_root(Path(__file__))
    monkeypatch.setattr(
        source_dev_run.source_dev_candidate_binding,
        "resolve",
        lambda _lane: (None, None),
    )
    monkeypatch.setattr(source_dev_run, "_claimed_root", lambda: (root, None))
    monkeypatch.setattr(
        source_dev_run.source_python_environment,
        "resolve",
        lambda _root, env: SourcePythonEnvironment(sys.executable, dict(env), {}),
    )
    monkeypatch.setattr(
        "yoke_core.tools.source_git_credentials.snapshot_git_helpers",
        lambda env, *_args: dict(env),
    )
    monkeypatch.setattr(db_admin_dsn_exec, "_require_postgres_profile", lambda _env: None)
    monkeypatch.setattr(db_admin_dsn_exec, "_resolve_dsn", lambda *_args: authority_dsn)
    monkeypatch.setattr(
        coordination,
        "detect",
        lambda: connector.Detection(connector.CONNECTOR_UNMANAGED, None, None, None),
    )
    snapshots = []
    original_run = source_dev_run.subprocess.run

    def record_run(args, **kwargs):
        env = kwargs.get("env", {})
        if env.get("YOKE_MACHINE_HOME") and env["YOKE_MACHINE_HOME"] != str(home):
            snapshots.append(Path(env["YOKE_MACHINE_HOME"]))
        return original_run(args, **kwargs)

    monkeypatch.setattr(source_dev_run.subprocess, "run", record_run)

    def source_runner(command, *, env):
        assert command[:4] == ["yoke", "dev", "run", "--"]
        with monkeypatch.context() as child:
            for key, value in env.items():
                child.setenv(key, value)
            return SimpleNamespace(returncode=source_dev_run.run(command[4:]))

    try:
        with psycopg.connect(authority_dsn) as conn:
            conn.execute("CREATE TABLE copy_evidence (value TEXT)")
            conn.execute("INSERT INTO copy_evidence VALUES ('copied')")
        command = [
            "yoke",
            "dev",
            "run",
            "--",
            "python3",
            "-m",
            "runtime.api.tools.authority_validation_copy",
        ]
        assert (
            db_admin_dsn_exec.run(
                "fixture-admin", "YOKE_PG_DSN", command, runner=source_runner
            )
            == 0
        )
        assert snapshots and all(not path.exists() for path in snapshots)
        path = binding.binding_file(binding.YOKE_VALIDATION_DSN_ENV)
        assert path.parent == secret.parent
        assert path.stat().st_mode & 0o777 == 0o600
        validation_dsn = binding.read_binding(binding.YOKE_VALIDATION_DSN_ENV)
        assert (
            psycopg.conninfo.conninfo_to_dict(validation_dsn)["dbname"]
            == validation_name
        )
        with psycopg.connect(validation_dsn) as conn:
            assert conn.execute("SELECT value FROM copy_evidence").fetchone() == (
                "copied",
            )
        # A new isolated source process uses the same resolver rehearsal uses.
        monkeypatch.setenv("YOKE_PG_DSN", authority_dsn)
        probe = (
            "import os, psycopg; "
            "from yoke_core.domain.migration_apply_targets import "
            "DbTarget, _resolve_external_postgres_validation as resolve; "
            "model={'runner': {'config': {'connection_env_var': 'YOKE_PG_DSN'}}}; "
            "target=resolve(model, 'primary', DbTarget('postgres', os.environ['YOKE_PG_DSN'], 'authority')); "
            "conn=psycopg.connect(target.target); "
            "assert conn.execute('SELECT value FROM copy_evidence').fetchone() == ('copied',); "
            "conn.close(); print('rehearsal binding ready')"
        )
        assert source_dev_run.run(["python3", "-c", probe]) == 0
        assert all(not path.exists() for path in snapshots)
        assert config.read_text() == "{}"
        assert secret.read_text() == "unchanged-secret"
        output = capfd.readouterr()
        assert "validation binding persisted:" in output.out
        assert "rehearsal binding ready" in output.out
        assert authority_dsn not in output.out + output.err
        assert validation_dsn not in output.out + output.err
    finally:
        transfer.drop_copy(copy_cluster, validation_name)
        transfer.drop_copy(copy_cluster, authority_name)
