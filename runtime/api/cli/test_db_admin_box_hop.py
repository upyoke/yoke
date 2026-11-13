"""The Yoke-owned SSH hop a box-mode db-admin profile reaches its VM through."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import db_admin_box_hop as hop
from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError

HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHostKeyFromTheVm"


def fake_hop(monkeypatch, *, ssh_rc: int = 0, ssh_stderr: str = "") -> list:
    """Replace ssh-keygen and ssh; return the recorded calls."""
    calls: list = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[0] == "ssh-keygen":
            key = Path(argv[argv.index("-f") + 1])
            key.write_text("PRIVATE KEY\n")
            Path(f"{key}.pub").write_text(
                f"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOperator {argv[argv.index('-C') + 1]}\n"
            )
            return subprocess.CompletedProcess(argv, 0, "", "")
        stdout = f"noise\n{hop.HOST_KEY_MARK}{HOST_KEY} root@vm\n" if ssh_rc == 0 else ""
        return subprocess.CompletedProcess(argv, ssh_rc, stdout, ssh_stderr)

    monkeypatch.setattr(hop, "_run", run)
    return calls


def _env(**overrides) -> SimpleNamespace:
    values = dict(
        project="platform", env_name="prod", ssh_user="ubuntu", mac_host="testy@mac-mini"
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    return tmp_path


def test_ensure_creates_key_authorizes_pins_and_writes_config(home, monkeypatch) -> None:
    calls = fake_hop(monkeypatch)

    report = hop.ensure(_env())

    key = home / "secrets" / "platform-prod-box-operator-ssh-key"
    assert report["operator_key_created"] is True
    assert report["alias"] == "yoke-prod-box"
    assert key.stat().st_mode & 0o777 == 0o600
    keygen, ssh = calls
    assert keygen[0][:4] == ["ssh-keygen", "-q", "-t", "ed25519"]
    argv, kwargs = ssh
    assert argv[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    assert argv[5] == "testy@mac-mini"
    assert "limactl" in argv[6] and "shell --workdir / yoke-prod sh -s" in argv[6]
    script = kwargs["input"]
    assert "U=ubuntu" in script
    assert 'grep -qxF "$K" "$F" ||' in script
    assert "/etc/ssh/ssh_host_ed25519_key.pub" in script
    assert "PRIVATE KEY" not in script

    known = (home / "ssh" / "known_hosts").read_text()
    assert known == f"yoke-prod-mini-vm {HOST_KEY}\n"
    config = (home / "ssh" / "config").read_text()
    assert "Host yoke-prod-box\n  User ubuntu\n" in config
    assert f'IdentityFile "{key}"' in config
    assert "HostKeyAlias yoke-prod-mini-vm" in config
    assert f'UserKnownHostsFile "{home / "ssh" / "known_hosts"}"' in config
    assert "StrictHostKeyChecking yes" in config
    assert "ProxyCommand ssh -o BatchMode=yes testy@mac-mini " in config
    assert "list yoke-prod --format \"{{.SSHLocalPort}}\"" in config
    assert "lima-*/bin/limactl" in config
    assert (home / "ssh" / "config").stat().st_mode & 0o777 == 0o600


def test_ensure_is_idempotent_and_keeps_other_environments(home, monkeypatch) -> None:
    calls = fake_hop(monkeypatch)
    hop.ensure(_env(env_name="stage"))
    hop.ensure(_env())
    calls.clear()

    report = hop.ensure(_env())

    assert report["operator_key_created"] is False
    assert [argv[0] for argv, _ in calls] == ["ssh"], "an existing key is reused"
    config = (home / "ssh" / "config").read_text()
    assert config.count("Host yoke-prod-box") == 1
    assert config.count("Host yoke-stage-box") == 1
    known = (home / "ssh" / "known_hosts").read_text().splitlines()
    assert sorted(line.split()[0] for line in known) == [
        "yoke-prod-mini-vm",
        "yoke-stage-mini-vm",
    ]


def test_unreachable_mac_host_refuses_naming_the_setting(home, monkeypatch) -> None:
    fake_hop(monkeypatch, ssh_rc=255, ssh_stderr="ssh: connect to host mac-mini: timed out")

    with pytest.raises(DbAdminSetupError) as excinfo:
        hop.ensure(_env())

    message = str(excinfo.value)
    assert message.startswith("box_mac_host_unreachable")
    assert "servers[0].mac_host (testy@mac-mini) of platform/prod" in message
    assert "timed out" in message
    assert not (home / "ssh" / "config").exists()


def test_failed_authorization_refuses_without_writing(home, monkeypatch) -> None:
    fake_hop(monkeypatch, ssh_rc=1, ssh_stderr="instance yoke-prod not found")

    with pytest.raises(DbAdminSetupError, match="box_operator_key_authorize_failed"):
        hop.ensure(_env())

    assert not (home / "ssh" / "known_hosts").exists()


@pytest.mark.parametrize(
    ("mac_host", "code"),
    [("", "box_mac_host_missing"), ("testy@mac mini; rm", "box_mac_host_invalid")],
)
def test_mac_host_setting_is_required_and_checked(home, monkeypatch, mac_host, code) -> None:
    calls = fake_hop(monkeypatch)

    with pytest.raises(DbAdminSetupError) as excinfo:
        hop.ensure(_env(mac_host=mac_host))

    assert str(excinfo.value).startswith(code)
    assert "servers[0].mac_host" in str(excinfo.value)
    assert calls == []
