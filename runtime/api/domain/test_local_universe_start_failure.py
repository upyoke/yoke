"""A failed local start names the tool that failed and only logs that exist."""

from __future__ import annotations

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
    monkeypatch.setattr(postgres_cluster, "initdb_if_needed", lambda _spec: LOADER)
    assert postgres_cluster.start_failure(spec) == StartFailure("initdb", LOADER)
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
