"""Rehearsal clients keep source credentials out of process arguments."""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.domain import migration_fleet_preflight_transfer as transfer


@pytest.mark.parametrize(
    "dsn",
    [
        "host=db port=5433 user=admin dbname=tenant password='dump secret' sslmode=require",
        "postgresql://admin:dump%20secret@db:5433/tenant?sslmode=require",
    ],
)
def test_dump_authenticates_only_through_child_environment(monkeypatch, tmp_path, dsn):
    monkeypatch.setenv("PGPASSWORD", "ambient-secret")
    monkeypatch.setenv("YOKE_PG_DSN", "password=ambient-secret")
    monkeypatch.setattr(transfer.postgres_cluster, "binary", lambda _spec, name: name)
    observed = {}

    class DumpProcess:
        returncode = 0

        def __init__(self, argv, **kwargs):
            observed.update(argv=argv, env=kwargs["env"])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def communicate(self, **_kwargs):
            return "", ""

    monkeypatch.setattr(transfer.subprocess, "Popen", DumpProcess)
    transfer.dump_database(
        SimpleNamespace(), dsn, tmp_path / "dump", source_environment="source-admin"
    )

    assert observed["argv"][0] == "pg_dump"
    assert all(
        "password=" not in arg and "dump secret" not in arg for arg in observed["argv"]
    )
    assert dsn not in observed["argv"]
    env = observed["env"]
    assert env["PGPASSWORD"] == "dump secret"
    assert env["PGHOST"] == "db"
    assert env["PGPORT"] == "5433"
    assert env["PGUSER"] == "admin"
    assert env["PGDATABASE"] == "tenant"
    assert env["PGSSLMODE"] == "require"
    assert env["PGKEEPALIVES"] == "1"
    assert "YOKE_PG_DSN" not in env
    assert os.environ["PGPASSWORD"] == "ambient-secret"


def test_passwordless_dump_does_not_inherit_another_connection(monkeypatch, tmp_path):
    monkeypatch.setenv("PGPASSWORD", "ambient-secret")
    observed = {}
    monkeypatch.setattr(transfer.postgres_cluster, "binary", lambda _spec, name: name)
    monkeypatch.setattr(
        transfer, "run_transfer", lambda _argv, **kwargs: observed.update(kwargs)
    )
    transfer.dump_database(
        SimpleNamespace(),
        "host=db dbname=tenant",
        tmp_path / "dump",
        source_environment="source-admin",
    )
    assert "PGPASSWORD" not in observed["env"]


def test_local_rehearsal_clients_have_only_nonsecret_connection_arguments(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(transfer.postgres_cluster, "binary", lambda _spec, name: name)

    def run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout="1; 2615 123 SCHEMA - extension admin\n", stderr=""
        )

    monkeypatch.setattr(transfer.subprocess, "run", run)
    spec = SimpleNamespace(sock_dir=tmp_path / "socket", superuser="admin")
    dump = tmp_path / "dump"
    transfer.create_copy(spec, "scratch")
    transfer.restore_copy(spec, "scratch", dump)
    transfer.restore_list_omitting_schemas(spec, dump, ["extension"], tmp_path / "list")
    transfer.drop_copy(spec, "scratch")
    transfer.postgres_cluster.psql(spec, "SELECT 1", "scratch")

    assert [argv[0] for argv in calls] == [
        "createdb",
        "pg_restore",
        "pg_restore",
        "dropdb",
        "psql",
    ]
    for argv in calls:
        assert all("password=" not in arg and "dump secret" not in arg for arg in argv)


def test_transfer_failure_redacts_password_without_full_conninfo(monkeypatch):
    monkeypatch.setattr(
        transfer.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv, 1, stderr="authentication failed: dump secret"
        ),
    )
    with pytest.raises(RuntimeError) as raised:
        transfer.run_transfer(["pg_dump"], timeout=1, env={"PGPASSWORD": "dump secret"})
    assert "dump secret" not in str(raised.value)
    assert "<redacted-secret>" in str(raised.value)
