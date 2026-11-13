"""Account login-shell selection when headless launchers omit SHELL."""

import builtins
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_contracts import shell_path_state as state


def account_shell(monkeypatch, shell):
    def getpwuid(uid):
        assert uid == state.os.getuid()
        return SimpleNamespace(pw_shell=shell)

    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwuid=getpwuid))


def test_explicit_shell_takes_precedence(monkeypatch):
    account_shell(monkeypatch, "/bin/bash")
    assert state.current_shell({"SHELL": "/usr/local/bin/fish"}) == "fish"


@pytest.mark.parametrize("env", [{}, {"SHELL": ""}])
def test_missing_shell_uses_account_login_shell(monkeypatch, env):
    account_shell(monkeypatch, "/bin/bash")
    assert state.current_shell(env) == "bash"


def test_default_environment_uses_account_login_shell(monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)
    account_shell(monkeypatch, "/bin/bash")
    assert state.current_shell() == "bash"


def test_empty_account_shell_uses_default(monkeypatch):
    account_shell(monkeypatch, "")
    assert state.current_shell({}) == "zsh"


def test_unknown_uid_uses_default(monkeypatch):
    def missing(uid):
        raise KeyError(uid)

    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwuid=missing))
    assert state.current_shell({}) == "zsh"


def test_pwd_unavailable_uses_default(monkeypatch):
    original_import = builtins.__import__

    def without_pwd(name, *args, **kwargs):
        if name == "pwd":
            raise ImportError("pwd unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pwd)
    assert state.current_shell({}) == "zsh"


def test_headless_bash_contract_selects_bash_startup_files(tmp_path, monkeypatch):
    account_shell(monkeypatch, "/bin/bash")
    contract = state.resolve_path_state_contract(env={"HOME": str(tmp_path)})
    assert contract.shell == "bash"
    assert contract.shell_path == "/bin/bash"
    assert contract.startup_file == str(tmp_path / ".profile")
    assert contract.ssh_startup_file == str(tmp_path / ".bashrc")


def test_path_fix_without_shell_probes_bash(tmp_path, monkeypatch, capsys):
    from yoke_cli.commands.adapters import path_doctor as cli
    from yoke_cli.config import path_doctor as doctor

    account_shell(monkeypatch, "/bin/bash")
    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    executable = tool_dir / "yoke"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tool_dir))
    monkeypatch.setattr(doctor, "SUPPORTED_SHELLS", ("bash",))
    calls = []

    def probe(command, **kwargs):
        assert command[0].endswith("/bash")
        assert doctor.MANAGED_BEGIN in (tmp_path / ".profile").read_text()
        assert doctor.MANAGED_BEGIN in (tmp_path / ".bashrc").read_text()
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, str(executable) + "\n", "")

    monkeypatch.setattr(doctor.terminal_detached_process, "run", probe)
    assert cli.path_fix(["--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True
    assert len(calls) >= 2
