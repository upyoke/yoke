"""Contributor commands use native executable paths and OS observations."""

from pathlib import Path
import os
import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.domain import source_pythonpath, source_postgres_environment
from yoke_core.tools import pg_testcluster, pg_testcluster_reclaim as reclaim
from yoke_cli.config import db_admin_box_hop as hop, db_admin_box_mac_host as mac_leg


def test_windows_executable_commands_keep_source_binding(monkeypatch):
    monkeypatch.setattr(source_pythonpath, "os", SimpleNamespace(name="nt"))
    assert source_pythonpath.bound_child_command(["python.exe", "-V"], python="bound") == ["bound", "-V"]
    assert source_pythonpath.bound_child_command(["yoke.exe", "--help"], python="bound") == ["bound", "-m", "yoke_cli.main", "--help"]


def test_windows_source_resources_find_initdb_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(source_postgres_environment, "os", SimpleNamespace(name="nt"))
    binaries = tmp_path / "postgres" / source_postgres_environment.POSTGRES_VERSION / "bin"
    binaries.mkdir(parents=True)
    (binaries / "initdb.exe").touch()
    result = source_postgres_environment.shared_postgres_environment({
        "YOKE_MACHINE_HOME": str(tmp_path), "YOKE_PG_CLUSTER_ROOT": str(tmp_path / "cluster"),
    })
    assert result["YOKE_PG_BIN_DIR"] == str(binaries)


def test_testcluster_accepts_windows_initdb_exe(monkeypatch, tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "initdb.exe").touch()
    spec = SimpleNamespace(bin_dir=binaries, sock_dir=tmp_path / "sock")
    monkeypatch.setattr(pg_testcluster, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(pg_testcluster, "_spec", lambda: spec)
    monkeypatch.setattr(pg_testcluster, "_is_ready", lambda: False)
    monkeypatch.setattr(pg_testcluster.postgres_cluster, "data_dir_major_mismatch", lambda _spec: None)
    monkeypatch.setattr(pg_testcluster.postgres_cluster, "initdb_if_needed", lambda _spec: 0)
    monkeypatch.setattr(pg_testcluster.postgres_cluster, "ensure_started", lambda _spec: 0)
    assert pg_testcluster.ensure_started() == 0


def test_reclaim_uses_same_owner_argv_without_parsing_shell_text(monkeypatch, tmp_path):
    binary = tmp_path / "Postgres binaries" / "postgres.exe"
    data = tmp_path / "cluster with spaces" / "data"

    def info(pid, owner, argv):
        return SimpleNamespace(pid=pid, username=owner, cmdline=tuple(argv))

    monkeypatch.setattr("yoke_contracts.platform_process.process_command_lines", lambda: [
        info(os.getpid(), "HOST\\contributor", ["python"]),
        info(1234, "HOST\\contributor", [str(binary), "-D", str(data)]),
        info(1235, "HOST\\someone-else", [str(binary), "-D", str(data)]),
        info(1236, "HOST\\contributor", ["postgres.exe", "-D", str(data)]),
    ])
    assert reclaim._postmasters() == [(1234, data.parent, binary.parent)]


def test_reclaim_refuses_unknown_process_owner(monkeypatch):
    monkeypatch.setattr("yoke_contracts.platform_process.process_command_lines", lambda: [])
    with pytest.raises(OSError, match="pgtest_owner_unknown"):
        reclaim._postmasters()


def test_windows_proxy_command_quotes_local_path_and_remote_shell(monkeypatch, tmp_path):
    config = tmp_path / "machine home" / "ssh" / "config"
    monkeypatch.setattr(hop, "config_path", lambda: config)
    monkeypatch.setattr(hop, "os", SimpleNamespace(name="nt"))
    remote = 'L=$(find "$HOME" -name limactl); exec "$L" list'
    assert hop._mac_ssh(SimpleNamespace(env_name="prod"), remote) == subprocess.list2cmdline([
        "ssh", "-F", str(config), "yoke-prod-mac-host", remote,
    ])


def test_ssh_host_block_normalizes_native_paths(monkeypatch):
    monkeypatch.setattr(mac_leg, "login", lambda env: ("user", "host"))
    monkeypatch.setattr(mac_leg, "key_path", lambda env: str(Path.home() / "key with spaces"))
    block = mac_leg.host_block(SimpleNamespace(env_name="prod"), str(Path.home() / "known hosts"))
    assert f'IdentityFile "{(Path.home() / "key with spaces").as_posix()}"' in block
    assert f'UserKnownHostsFile "{(Path.home() / "known hosts").as_posix()}"' in block


def test_windows_cluster_environment_uses_powershell_literals(monkeypatch, tmp_path):
    monkeypatch.setattr(pg_testcluster, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(pg_testcluster, "_root", lambda: tmp_path / "user's $cluster")
    monkeypatch.setattr(pg_testcluster, "dsn", lambda: "host=socket user=contributor")
    monkeypatch.setattr(pg_testcluster.postgres_binaries, "pinned_bin_dir", lambda: None)
    result = pg_testcluster.env_block()
    assert "$env:YOKE_PG_CLUSTER_ROOT = '" in result
    assert "user''s $cluster'" in result
    assert "$env:YOKE_PG_DSN = 'host=socket user=contributor'" in result
