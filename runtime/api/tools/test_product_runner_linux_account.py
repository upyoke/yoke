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
        return SimpleNamespace(returncode=0, stdout=linger + "\n", stderr="")

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
    monkeypatch.setattr(smoke, "verified_account_environment", lambda: (home, bus))
    env = smoke.isolated_environment(tmp_path, tmp_path / "venv")
    assert env["HOME"] == str(home)
    assert env["YOKE_MACHINE_HOME"] == str(home / ".yoke")
    assert env.items() >= bus.items()
    assert "GH_TOKEN" not in env


def test_account_login_and_teardown_survive_failed_smoke(monkeypatch, tmp_path):
    scratch = tmp_path / "account"
    scratch.mkdir()
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)
    output = tmp_path / "workspace" / "product-smoke-evidence"
    output.parent.mkdir()
    monkeypatch.setattr(account, "sys", SimpleNamespace(platform="linux", executable="/bin/python3"))
    monkeypatch.setattr(account, "os", SimpleNamespace(
        getuid=lambda: 0, getpid=lambda: 99, environ={"GITHUB_ACTIONS": "true"}, pathsep=":", defpath="/bin:/usr/bin",
    ))
    monkeypatch.setattr(account, "SUDOERS_ROOT", tmp_path)
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwnam=lambda user: SimpleNamespace(pw_uid=1234)))
    monkeypatch.setattr(account.tempfile, "TemporaryDirectory", lambda **kwargs: nullcontext(str(scratch)))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "systemd-run":
            evidence = Path(argv[-1])
            evidence.mkdir()
            (evidence / "report.json").write_text("{}")
        return SimpleNamespace(returncode=7 if argv[0] == "systemd-run" else 0)

    monkeypatch.setattr(account.subprocess, "run", run)
    assert account.run_account(root, output, Path("/tools/uv"), "Ubuntu 24.04", "arm64") == 7
    login = next(argv for argv in calls if argv[0] == "systemd-run")
    home = scratch / "home"
    assert "--property=PAMName=login" in login
    assert f"--working-directory={home / 'checkout'}" in login
    assert f"--setenv={account.ACCOUNT_HOME}={home}" in login
    # PAM's user manager supplies the bus; the launcher never fabricates it.
    assert not any("XDG_RUNTIME_DIR" in arg or "DBUS_SESSION" in arg for arg in login)
    # pam_env rewrites PATH, so the tool path is set by env after PAM runs.
    assert not any(arg.startswith("--setenv=PATH") for arg in login)
    assert login[login.index("/usr/bin/env") + 1].startswith("PATH=/tools:")
    assert (home / "checkout" / ".git").is_dir()
    assert (output / "report.json").read_text() == "{}"
    assert ["chown", "-R", "yksmoke99:", str(scratch)] in calls
    assert calls[-4][:2] == ["chown", "-R"] and calls[-4][-1] == str(output)
    assert calls[-3][0:2] == ["loginctl", "terminate-user"]
    assert calls[-2] == ["systemctl", "stop", "user@1234.service"]
    assert calls[-1] == ["userdel", "yksmoke99"]
    assert not (tmp_path / "yoke-smoke-1234").exists()
    assert all("enable-linger" not in argv for argv in calls)


def test_launcher_refuses_outside_disposable_linux_ci(monkeypatch, tmp_path):
    monkeypatch.setattr(account, "os", SimpleNamespace(getuid=lambda: 1000, environ={}))
    with pytest.raises(account.AccountRefused, match="smoke_account_requires_disposable_linux_runner"):
        account.run_account(tmp_path, tmp_path / "out", Path("/uv"), "Ubuntu 24.04", "arm64")
