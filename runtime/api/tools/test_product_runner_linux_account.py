"""Linux smoke uses an actual disposable login without borrowing host authority."""

from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from runtime.api.tools import product_runner_linux_account as account
from runtime.api.tools import product_runner_smoke as smoke


def facts(monkeypatch, tmp_path, *, linger="no", passwd_home=None):
    env = {
        account.ACCOUNT_HOME: str(tmp_path),
        "XDG_RUNTIME_DIR": "/run/user/1234",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1234/bus",
    }
    monkeypatch.setattr(account, "os", SimpleNamespace(environ=env, getuid=lambda: 1234))
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(
        getpwuid=lambda uid: SimpleNamespace(pw_dir=str(passwd_home or tmp_path)),
    ))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=linger + "\n")

    monkeypatch.setattr(account.subprocess, "run", run)
    return env, calls


def test_verified_login_home_keeps_only_its_bus(monkeypatch, tmp_path):
    _, calls = facts(monkeypatch, tmp_path)
    home, env = account.verified_account_environment()
    assert home == tmp_path.resolve()
    assert env == {"XDG_RUNTIME_DIR": "/run/user/1234", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1234/bus"}
    assert calls == [["systemctl", "--user", "show-environment"],
                     ["loginctl", "show-user", "1234", "--property=Linger", "--value"]]


@pytest.mark.parametrize("fault", ["home", "bus", "linger"])
def test_service_proof_refuses_mismatched_account_or_logout_policy(monkeypatch, tmp_path, fault):
    env, _ = facts(monkeypatch, tmp_path, linger="yes" if fault == "linger" else "no",
                   passwd_home=tmp_path / "other" if fault == "home" else None)
    if fault == "bus":
        env["XDG_RUNTIME_DIR"] = "/run/user/another-account"
    with pytest.raises(RuntimeError, match="smoke_account_"):
        account.verified_account_environment()


def test_linux_child_uses_verified_home_without_inheriting_tokens(monkeypatch, tmp_path):
    home = tmp_path / "account-home"
    home.mkdir()
    monkeypatch.setattr(smoke.sys, "platform", "linux")
    monkeypatch.setenv(account.ACCOUNT_HOME, str(home))
    monkeypatch.setenv("GH_TOKEN", "host-authority")
    bus = {"XDG_RUNTIME_DIR": "/run/user/1234", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1234/bus"}
    monkeypatch.setattr(account, "verified_account_environment", lambda: (home, bus))
    env = smoke.isolated_environment(tmp_path, tmp_path / "venv")
    assert env["HOME"] == str(home)
    assert env["YOKE_MACHINE_HOME"] == str(home / ".yoke")
    assert env.items() >= bus.items()
    assert "GH_TOKEN" not in env


def test_account_login_and_teardown_survive_failed_smoke(monkeypatch, tmp_path):
    scratch = tmp_path / "account"
    scratch.mkdir()
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(account, "sys", SimpleNamespace(platform="linux", executable="/bin/python3"))
    monkeypatch.setattr(account, "os", SimpleNamespace(
        getuid=lambda: 0, getpid=lambda: 99, environ={"GITHUB_ACTIONS": "true"}, pathsep=":", defpath="/bin:/usr/bin",
    ))
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwnam=lambda user: SimpleNamespace(pw_uid=1234)))
    monkeypatch.setattr(account.tempfile, "TemporaryDirectory", lambda **kwargs: nullcontext(str(scratch)))
    monkeypatch.setattr(account, "SUDOERS_ROOT", tmp_path)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=7 if argv[0] == "systemd-run" else 0)

    monkeypatch.setattr(account.subprocess, "run", run)
    assert account.run_account(root, root / "evidence", Path("/tools/uv"), "Ubuntu 24.04", "arm64") == 7
    login = next(argv for argv in calls if argv[0] == "systemd-run")
    assert "--property=PAMName=login" in login
    assert f"HOME={scratch / 'home'}" in login
    assert "XDG_RUNTIME_DIR=/run/user/1234" in login
    assert calls[-4][0:2] == ["loginctl", "terminate-user"]
    assert calls[-3] == ["systemctl", "stop", "user@1234.service"]
    assert calls[-2] == ["userdel", "yksmoke99"]
    assert calls[-1][0:2] == ["chown", "-R"]
    assert all("enable-linger" not in argv for argv in calls)

    assert not (tmp_path / "yoke-smoke-1234").exists()
