"""A failed local start names the tool that failed and only logs that exist."""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.domain import local_universe
from yoke_core.domain import postgres_cluster
from yoke_core.domain.postgres_cluster_process import LOADER_HINT, StartFailure

LOADER = 0xC0000135


def _fail_with(monkeypatch, tmp_path, failure):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    bin_dir = tmp_path / "engine" / "bin"
    bin_dir.mkdir(parents=True)
    monkeypatch.setattr(local_universe, "ensure_engine_binaries", lambda emit: bin_dir)
    monkeypatch.setattr(postgres_cluster, "start_failure", lambda _spec: failure)


def test_initdb_loader_failure_names_initdb_and_hint_not_server_log(
    monkeypatch, tmp_path
):
    _fail_with(monkeypatch, tmp_path, StartFailure("initdb", LOADER))
    with pytest.raises(local_universe.LocalUniverseError) as raised:
        local_universe.start()
    message = str(raised.value)
    assert "initdb exited 0xC0000135" in message
    assert "server.log" not in message
    assert message.endswith(LOADER_HINT)


def test_pg_ctl_failure_names_server_log_once_it_exists(monkeypatch, tmp_path):
    _fail_with(monkeypatch, tmp_path, StartFailure("pg_ctl", 1))
    log_file = local_universe.cluster_spec().log_file
    log_file.parent.mkdir(parents=True)
    log_file.write_text("FATAL: lock file exists\n", encoding="utf-8")
    with pytest.raises(local_universe.LocalUniverseError) as raised:
        local_universe.start()
    assert str(raised.value) == (
        f"embedded Postgres failed to start: pg_ctl exited 0x00000001; see {log_file}."
    )


def test_cluster_start_reports_which_tool_failed(monkeypatch, tmp_path):
    spec = local_universe.cluster_spec(root=tmp_path / "universe")
    failure = StartFailure("initdb", LOADER)
    monkeypatch.setattr(postgres_cluster, "initdb_if_needed", lambda _spec: failure)
    assert postgres_cluster.start_failure(spec) == failure
    assert postgres_cluster.ensure_started(spec) == LOADER


def test_apply_report_carries_the_loader_hint(monkeypatch, tmp_path):
    from yoke_cli.config import onboard_apply_connection

    _fail_with(monkeypatch, tmp_path, StartFailure("initdb", LOADER))

    class ApplyError(Exception):
        pass

    with pytest.raises(ApplyError) as raised:
        onboard_apply_connection.apply_local_universe(
            tmp_path / "home" / "config.json",
            "local",
            {},
            None,
            {},
            admin_name="Ada",
            error_cls=ApplyError,
        )
    assert "initdb exited 0xC0000135" in str(raised.value)
    assert "embedded_postgres_load_failed" in str(raised.value)
    assert "server.log" not in str(raised.value)


def test_pg_ctl_start_failure_preserves_the_denial_without_printing_it(monkeypatch, tmp_path, capsys):
    spec = local_universe.cluster_spec(root=tmp_path / "universe")
    denial = 'pg_ctl: could not open log file "server.log": Operation not permitted'
    monkeypatch.setattr(postgres_cluster, "initdb_if_needed", lambda _spec: None)
    monkeypatch.setattr(postgres_cluster, "is_ready", lambda _spec: False)
    monkeypatch.setattr(
        postgres_cluster, "start_server",
        lambda _spec: subprocess.CompletedProcess(["pg_ctl"], 1, "", denial),
    )
    _fail_with(monkeypatch, tmp_path, postgres_cluster.start_failure(spec))
    with pytest.raises(local_universe.LocalUniverseError, match="Operation not permitted"):
        local_universe.start()
    assert capsys.readouterr().err == ""


def test_application_control_launch_denial_refuses_local_start_by_name(monkeypatch, tmp_path):
    from yoke_core.domain import postgres_cluster_process

    def denied(argv, **kw):
        exc = OSError(None, "This program is blocked by group policy.")
        exc.winerror = 1260  # set on every OS; only Windows fills it from the constructor
        raise exc

    monkeypatch.setattr(postgres_cluster_process.terminal_detached_process, "run", denied)
    spec = local_universe.cluster_spec(root=tmp_path / "universe")
    failure = postgres_cluster.start_failure(spec)
    assert failure.tool == "initdb" and failure.returncode == 1
    _fail_with(monkeypatch, tmp_path, failure)
    with pytest.raises(local_universe.LocalUniverseError) as raised:
        local_universe.start()
    message = str(raised.value)
    assert "windows_application_control_denied" in message
    assert "initdb" in message and "WinError 1260" in message


def test_other_launch_errors_still_raise(monkeypatch):
    from yoke_core.domain import postgres_cluster_process

    def missing(argv, **kw):
        raise FileNotFoundError(2, "No such file", argv[0])

    monkeypatch.setattr(postgres_cluster_process.terminal_detached_process, "run", missing)
    with pytest.raises(FileNotFoundError):
        postgres_cluster_process._run(["initdb"])
