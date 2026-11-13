"""The Yoke-owned SSH hop a box-mode db-admin profile reaches its VM through."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import db_admin_box_hop as hop
from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError

HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHostKeyFromTheVm"
MAC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMacHostKey"
MAC_FINGERPRINT = "SHA256:" + "K" * 43


def fake_hop(monkeypatch, *, ssh_rc: int = 0, ssh_stderr: str = "") -> list:
    """Replace ssh-keygen, ssh-keyscan and ssh; return the recorded calls."""
    calls: list = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[0] == "ssh-keyscan":
            other = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQOther"
            return subprocess.CompletedProcess(
                argv, 0, f"{argv[-1]} {other}\n{argv[-1]} {MAC_KEY}\n", ""
            )
        if argv[:2] == ["ssh-keygen", "-l"]:
            key = Path(argv[-1]).read_text()
            fp = MAC_FINGERPRINT if MAC_KEY in key else "SHA256:" + "o" * 43
            return subprocess.CompletedProcess(argv, 0, f"256 {fp} no comment (X)\n", "")
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
        project="platform",
        env_name="prod",
        ssh_user="ubuntu",
        mac_host="testy@mac-mini",
        mac_host_ssh_key_path="~/.ssh/operator_rsa",
        mac_host_key_fingerprint=MAC_FINGERPRINT,
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
    keygen = calls[0]
    assert keygen[0][:4] == ["ssh-keygen", "-q", "-t", "ed25519"]
    assert calls[1][0][:2] == ["ssh-keyscan", "-T"] and calls[1][0][-1] == "mac-mini"
    argv, kwargs = calls[-1]
    assert argv[:3] == ["ssh", "-F", str(home / "ssh" / "config")]
    assert argv[5] == "yoke-prod-mac-host"
    assert "limactl" in argv[6] and "shell --workdir / yoke-prod sh -s" in argv[6]
    script = kwargs["input"]
    assert "U=ubuntu" in script
    assert 'grep -qxF "$K" "$F" ||' in script
    assert "/etc/ssh/ssh_host_ed25519_key.pub" in script
    assert "PRIVATE KEY" not in script

    known = (home / "ssh" / "known_hosts").read_text()
    assert known == f"yoke-prod-mac-host {MAC_KEY}\nyoke-prod-mini-vm {HOST_KEY}\n"
    config = (home / "ssh" / "config").read_text()
    mac_block = (
        "Host yoke-prod-mac-host\n  HostName mac-mini\n  User testy\n"
        f'  IdentityFile "{Path("~/.ssh/operator_rsa").expanduser()}"\n'
        "  IdentitiesOnly yes\n  HostKeyAlias yoke-prod-mac-host\n"
    )
    assert mac_block in config
    assert "Host yoke-prod-box\n  User ubuntu\n" in config
    assert f'IdentityFile "{key}"' in config
    assert "HostKeyAlias yoke-prod-mini-vm" in config
    assert f'UserKnownHostsFile "{home / "ssh" / "known_hosts"}"' in config
    assert "StrictHostKeyChecking yes" in config
    assert f"ProxyCommand ssh -F {home / 'ssh' / 'config'} yoke-prod-mac-host " in config
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
    assert "-q" not in [part for argv, _ in calls for part in argv], "key reused"
    config = (home / "ssh" / "config").read_text()
    for name in ("prod-box", "stage-box", "prod-mac-host", "stage-mac-host"):
        assert config.count(f"Host yoke-{name}\n") == 1
    known = (home / "ssh" / "known_hosts").read_text().splitlines()
    assert sorted(line.split()[0] for line in known) == [
        "yoke-prod-mac-host",
        "yoke-prod-mini-vm",
        "yoke-stage-mac-host",
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
    assert "yoke-prod-mini-vm" not in (home / "ssh" / "known_hosts").read_text()


def test_failed_authorization_refuses_without_writing(home, monkeypatch) -> None:
    fake_hop(monkeypatch, ssh_rc=1, ssh_stderr="instance yoke-prod not found")

    with pytest.raises(DbAdminSetupError, match="box_operator_key_authorize_failed"):
        hop.ensure(_env())

    assert "yoke-prod-mini-vm" not in (home / "ssh" / "known_hosts").read_text()


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"mac_host": ""}, "box_mac_host_missing"),
        ({"mac_host": "testy@mac mini; rm"}, "box_mac_host_invalid"),
        ({"mac_host": "mac-mini"}, "box_mac_host_invalid"),
        ({"mac_host_ssh_key_path": ""}, "box_mac_host_ssh_key_path_missing"),
        ({"mac_host_key_fingerprint": ""}, "box_mac_host_key_fingerprint_missing"),
        ({"mac_host_key_fingerprint": "abc"}, "box_mac_host_key_fingerprint_invalid"),
    ],
)
def test_mac_host_settings_are_required_and_checked(home, monkeypatch, override, code) -> None:
    calls = fake_hop(monkeypatch)

    with pytest.raises(DbAdminSetupError) as excinfo:
        hop.ensure(_env(**override))

    assert str(excinfo.value).startswith(code)
    assert "servers[0]." in str(excinfo.value)
    assert calls == []


def test_mac_host_key_must_match_the_declared_fingerprint(home, monkeypatch) -> None:
    calls = fake_hop(monkeypatch)

    with pytest.raises(DbAdminSetupError) as excinfo:
        hop.ensure(_env(mac_host_key_fingerprint="SHA256:" + "z" * 43))

    assert str(excinfo.value).startswith("box_mac_host_key_mismatch")
    assert "servers[0].mac_host_key_fingerprint" in str(excinfo.value)
    assert not (home / "ssh" / "known_hosts").exists()
    assert not any(argv[0] == "ssh" for argv, _ in calls), "no login before the pin"
