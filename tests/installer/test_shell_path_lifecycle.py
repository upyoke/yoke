"""Shell startup, repair idempotency and precise uninstall ownership."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from yoke_cli.config import path_doctor as doctor
from yoke_cli.config.path_state_contract import (
    MANAGED_BEGIN,
    remove_shell_path,
    shell_setup_files,
)


def environment(home):
    bindir = home / "tools with spaces"
    bindir.mkdir()
    executable = bindir / "yoke"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    return {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "SHELL": "/bin/zsh",
        "UV_TOOL_BIN_DIR": str(bindir),
        "BASH_ENV": str(home / "user-env"),
        "ZDOTDIR": str(home / "zsh"),
        "XDG_CONFIG_HOME": str(home / "config"),
    }


def test_reinstall_and_uninstall_preserve_unrelated_bytes_and_symlinks(tmp_path):
    env = environment(tmp_path)
    files = shell_setup_files(env)
    originals = {}
    for file in files:
        file.parent.mkdir(parents=True, exist_ok=True)
        originals[file] = b"# user settings\r\nexport USER_SETTING=yes\r\n"
        file.write_bytes(originals[file])
    rc = tmp_path / ".bashrc"
    target = tmp_path / "linked-bashrc"
    rc.rename(target)
    rc.symlink_to(target)
    doctor.update_shell(env=env)
    first = {file: file.read_bytes() for file in files}
    doctor.update_shell(env=env)
    assert first == {file: file.read_bytes() for file in files}
    assert all(text.count(MANAGED_BEGIN.encode()) == 1 for text in first.values())
    assert rc.is_symlink()
    remove_shell_path(env=env)
    assert originals == {file: file.read_bytes() for file in files}
    assert rc.is_symlink()
    assert remove_shell_path(env=env) == []


@pytest.mark.parametrize("shell", ("zsh", "bash", "fish"))
def test_supported_shell_contexts_resolve_without_duplicate_path(tmp_path, shell):
    executable = shutil.which(shell)
    if not executable:
        pytest.skip(f"{shell} unavailable")
    env = environment(tmp_path)
    env["SHELL"] = executable
    # SSH must reach the PATH block even with the usual interactive guard.
    (tmp_path / ".bashrc").write_text("case $- in *i*) ;; *) return ;; esac\n")
    doctor.update_shell(env=env)
    for context, flag in (
        ("login", "-lic"),
        ("interactive", "-ic"),
        ("non-login", "-c"),
    ):
        rows = doctor._verify_shell(
            flag,
            shell,
            env=env,
            child_shell=shell == "bash" and context == "non-login",
        )
        assert {row.name: row.path for row in rows}["yoke"] == str(
            Path(env["UV_TOOL_BIN_DIR"]) / "yoke"
        ), context
    rows = doctor.verify_ssh_command(shell, env=env)
    assert {row.name: row.path for row in rows}["yoke"]
    if shell == "bash":
        result = subprocess.run(
            [
                executable,
                "--noprofile",
                "--norc",
                "-c",
                '. "$HOME/.bashrc"; . "$HOME/.bashrc"; printf "%s\\n%s" "$PATH" "$BASH_ENV"',
            ],
            env={**env, "SSH_CLIENT": "127.0.0.1 0 22"},
            text=True,
            capture_output=True,
            check=True,
        )
        path_value, bash_env = result.stdout.split("\n", 1)
        assert path_value.split(os.pathsep).count(env["UV_TOOL_BIN_DIR"]) == 1
        assert bash_env == env["BASH_ENV"]


def test_diagnosis_aggregates_ssh_failure_when_login_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(
        doctor,
        "verify_fresh_login",
        lambda *a, **kw: [doctor.ToolResolution("yoke", "/test/yoke")],
    )
    monkeypatch.setattr(doctor, "verify_ssh_command", lambda *a, **kw: [])
    diagnosis = doctor.diagnose(
        env={"HOME": str(tmp_path), "SHELL": "/bin/zsh", "PATH": "/usr/bin:/bin"}
    )
    assert diagnosis.login_needs_fix is False
    assert diagnosis.ssh_needs_fix is True
    assert diagnosis.needs_fix is True


def test_invalid_marker_refuses_cleanup_with_recovery(tmp_path):
    env = environment(tmp_path)
    rc = tmp_path / ".bashrc"
    rc.write_text(MANAGED_BEGIN + "\nuser text\n")
    before = rc.read_bytes()
    with pytest.raises(OSError, match="shell_path_cleanup_failed.*retry uninstall"):
        remove_shell_path(env=env)
    assert rc.read_bytes() == before


def test_probe_timeout_names_context_and_recovery(tmp_path, monkeypatch):
    from yoke_cli.config.path_shell_contexts import diagnose_contexts

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 10)

    monkeypatch.setattr(doctor.terminal_detached_process, "run", timeout)
    rows = diagnose_contexts(
        {"HOME": str(tmp_path), "SHELL": "/bin/zsh", "PATH": "/bin:/usr/bin"},
        (str(tmp_path / "bin"),),
    )
    assert rows
    assert all(
        row["needs_fix"] and row["reason"] == "shell_probe_timeout" for row in rows
    )
    assert all("yoke path fix" in row["recovery"] for row in rows)
