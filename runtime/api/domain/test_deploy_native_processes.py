"""Deploy forwarding and Windows OpenSSH permissions at process boundaries."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import deploy_database_tunnel as tunnels
from yoke_core.domain import deploy_remote, ssh_identity
from runtime.api.domain.deploy_remote_test_support import FakeRunner, _env


def test_deploy_tunnel_preserves_bind_host_and_ipv6_destination():
    runner = FakeRunner()
    forward = "127.0.0.1:54441:[::1]:5432"
    tunnels.open_db_tunnel(runner, _env(), forward)
    argv = runner.calls[0]["argv"]
    assert argv[argv.index("-L") + 1] == forward
    assert "-N" in argv and "-f" not in argv
    tunnels.close_db_tunnel(runner, forward)
    assert runner.calls[1]["argv"] == ["stop-ssh-forward", forward]


def test_deploy_close_targets_only_the_exact_ssh_forward(monkeypatch):
    spec = "127.0.0.1:54441:database:5432"
    processes = [
        SimpleNamespace(pid=11, cmdline=("ssh.exe", "-L", spec, "host")),
        SimpleNamespace(pid=12, cmdline=("ssh", "-L" + spec, "host")),
        SimpleNamespace(pid=13, cmdline=("python", "-L", spec, "host")),
        SimpleNamespace(pid=14, cmdline=("ssh", "-L", spec + "0", "host")),
    ]
    monkeypatch.setattr(tunnels.lifecycle, "process_command_lines", lambda: processes)
    stopped = []
    monkeypatch.setattr(
        tunnels.lifecycle,
        "_terminate_pids",
        lambda pids, timeout: stopped.append((pids, timeout)),
    )
    tunnels.stop_forward(spec, timeout=7)
    assert stopped == [([11, 12], 7)]


def test_windows_private_key_refuses_before_launch(monkeypatch, tmp_path):
    key = tmp_path / "operator.pem"
    monkeypatch.setattr(ssh_identity, "_NATIVE_WINDOWS", True)
    monkeypatch.setattr(ssh_identity, "is_owner_private_file", lambda path: False)
    monkeypatch.setattr(
        deploy_remote.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("launched insecure identity"),
    )
    with pytest.raises(
        RuntimeError, match="ssh_identity_not_private.*Windows Security"
    ):
        deploy_remote.CommandRunner().run(["ssh", "-i", str(key), "host", "true"])


def test_windows_private_key_accepts_private_acl(monkeypatch, tmp_path):
    monkeypatch.setattr(ssh_identity, "_NATIVE_WINDOWS", True)
    monkeypatch.setattr(
        ssh_identity, "is_owner_private_file", lambda path: path == tmp_path / "key"
    )
    ssh_identity.validate_identity(["ssh.exe", "-i", str(tmp_path / "key"), "host"])


def test_posix_key_permissions_stay_with_openssh(monkeypatch):
    monkeypatch.setattr(ssh_identity, "_NATIVE_WINDOWS", False)
    monkeypatch.setattr(
        ssh_identity,
        "is_owner_private_file",
        lambda path: pytest.fail("Windows ACL check on POSIX"),
    )
    ssh_identity.validate_identity(["ssh", "-i", "/keys/identity", "host"])
