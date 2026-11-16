"""Non-login hook shell command coverage."""

from __future__ import annotations

import shlex
import os
import subprocess
from pathlib import Path

from yoke_contracts.hook_shell_command import hook_shell_command
import pytest


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell execution")
def test_hook_shell_avoids_startup_files_and_sets_launcher_path(tmp_path: Path) -> None:
    launcher_bin = tmp_path / "launcher-bin"
    launcher_bin.mkdir()
    launcher = launcher_bin / "yoke"
    launcher.write_text("#!/bin/sh\nprintf '%s' \"$1\"\n", encoding="utf-8")
    launcher.chmod(0o755)
    command = hook_shell_command("yoke hook-ok")
    argv = shlex.split(command)

    assert argv[:2] == ["/bin/sh", "-c"]
    assert "/bin/zsh" not in command
    assert " -l" not in command
    assert "${XDG_BIN_HOME:-$HOME/.local/bin}" in command
    assert "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" in command
    completed = subprocess.run(
        argv,
        env={
            "HOME": str(tmp_path),
            "XDG_BIN_HOME": str(launcher_bin),
            "PATH": "/bin",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout == "hook-ok"


def test_hook_shell_rejects_unquoted_source() -> None:
    try:
        hook_shell_command("printf 'unsafe'")
    except ValueError as exc:
        assert "single quote" in str(exc)
    else:
        raise AssertionError("single-quoted hook source was accepted")


@pytest.mark.parametrize("harness", ["claude-code", "codex", "cursor"])
def test_windows_commands_are_shell_safe_and_keep_context(harness):
    from yoke_contracts.hook_shell_command import (
        hook_command_source,
        windows_hook_command,
    )

    command = windows_hook_command(
        harness, "PreToolUse", "machine", resilient=harness == "cursor"
    )
    source = hook_command_source(command)
    assert command.startswith(
        "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
    )
    assert len(shlex.split(command)) == 6
    assert "$" not in command and "|" not in command
    assert "$env:YOKE_ROOT=$root" in source
    assert "$env:YOKE_HOOK_CONFIG_OWNER='machine'" in source
    assert "& yoke hook evaluate PreToolUse; exit $LASTEXITCODE" in source
    assert "Set-Location -LiteralPath" in source if harness == "cursor" else True


def test_codex_renders_windows_command_and_hashes_the_selected_command(monkeypatch):
    from yoke_contracts import codex_hook_trust as trust
    from yoke_contracts import hook_shell_command as shell
    from yoke_core.domain.agents_render_hooks import render_codex_hooks_block

    document = {"hooks": render_codex_hooks_block()}
    handler = document["hooks"]["Stop"][0]["hooks"][0]
    assert handler["command"].startswith("/bin/sh")
    assert handler["commandWindows"].startswith("powershell.exe")
    posix_hash = trust.codex_hook_hashes_from_document(document)
    monkeypatch.setattr(trust.os, "name", "nt")
    windows_hash = trust.codex_hook_hashes_from_document(document)
    assert windows_hash != posix_hash
    assert "yoke hook evaluate Stop" in shell.hook_command_source(
        handler["commandWindows"]
    )


def test_doctor_selects_windows_command_and_names_missing_shell(monkeypatch):
    from yoke_contracts import hook_shell_command as shell

    monkeypatch.setattr(shell.os, "name", "nt")
    monkeypatch.setattr(
        shell.shutil, "which", lambda name: name if name == "powershell.exe" else None
    )
    handler = {
        "command": "/bin/sh -c yoke",
        "commandWindows": "powershell.exe -NoProfile",
    }
    assert shell.hook_command_start_problem(handler, codex=True) == ""
    assert "hook_command_unstartable" in shell.hook_command_start_problem(handler)


def test_codex_trust_remints_when_the_windows_command_changes(tmp_path):
    import json
    from yoke_contracts.codex_hook_trust_store import (
        inspect_hook_file_trust,
        mint_installed_checkout_trust,
    )
    from yoke_contracts.hook_shell_command import windows_hook_command

    hooks = tmp_path / ".codex" / "hooks.json"
    hooks.parent.mkdir()
    config = tmp_path / "codex-config.toml"
    handler = {"type": "command", "command": "yoke hook evaluate Stop"}
    hooks.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [handler]}]}}), encoding="utf-8"
    )
    mint_installed_checkout_trust(tmp_path, config_path=config)
    assert inspect_hook_file_trust(hooks, config_path=config).approved

    handler["commandWindows"] = windows_hook_command("codex", "Stop", None)
    hooks.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [handler]}]}}), encoding="utf-8"
    )
    mint_installed_checkout_trust(tmp_path, config_path=config)
    assert inspect_hook_file_trust(hooks, config_path=config).approved


def test_windows_install_renders_linux_server_bundle_without_changing_policy(
    monkeypatch,
):
    from copy import deepcopy
    from yoke_cli.project_install import hook_platform
    from yoke_core.domain.install_bundle import _hooks_block
    from yoke_contracts.hook_shell_command import hook_command_source

    bundle = {"hooks": _hooks_block(), "files": [{"path": "unchanged"}]}
    original = deepcopy(bundle)
    monkeypatch.setattr(hook_platform.os, "name", "nt")
    native = hook_platform.native_bundle_hooks(bundle)
    assert bundle == original
    assert native["files"] == bundle["files"]
    for key, events in native["hooks"].items():
        assert events.keys() == bundle["hooks"][key].keys()
        for event, entries in events.items():
            for index, entry in enumerate(entries):
                old = bundle["hooks"][key][event][index]
                assert entry.get("matcher") == old.get("matcher")
                for handler in entry.get("hooks", [entry]):
                    command = (
                        handler["commandWindows"]
                        if key == "codex_hooks"
                        else handler["command"]
                    )
                    assert command.startswith("powershell.exe")
                    assert "yoke hook evaluate" in hook_command_source(command)


def test_refresh_replaces_codex_entry_when_only_windows_command_changes(tmp_path):
    import json
    from copy import deepcopy
    from yoke_cli.project_install import hooks
    from yoke_cli.project_install.hook_entries import provided_records

    old = {"Stop": [{"hooks": [{"type": "command", "command": "echo posix"}]}]}
    target = tmp_path / ".codex" / "hooks.json"
    target.parent.mkdir()
    target.write_text(json.dumps({"hooks": old}), encoding="utf-8")
    updated = deepcopy(old)
    updated["Stop"][0]["hooks"][0]["commandWindows"] = "echo windows"
    result = hooks.plan_hooks_file(
        tmp_path,
        ".codex/hooks.json",
        updated,
        provided_records(old),
        created_by_install=True,
    )
    assert result["payload"]["hooks"] == updated
    assert result["changed"]


@pytest.mark.skipif(os.name != "nt", reason="executes native Windows PowerShell")
@pytest.mark.parametrize("harness", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("shell", ["native", "git-bash"])
def test_native_windows_command_keeps_stdin_paths_and_exit_status(
    tmp_path, harness, shell
):
    import json
    import shutil
    import sys
    from yoke_contracts.hook_shell_command import windows_hook_command

    bin_dir = tmp_path / "launcher bin"
    project = tmp_path / "project with spaces"
    bin_dir.mkdir()
    project.mkdir()
    probe = bin_dir / "probe.py"
    probe.write_text(
        "import json, os, sys\n"
        "print(json.dumps({'root': os.environ['YOKE_ROOT'], 'stdin': sys.stdin.read(), "
        "'args': sys.argv[1:]}))\nsys.exit(7)\n",
        encoding="utf-8",
    )
    (bin_dir / "yoke.cmd").write_text(
        f'@"{sys.executable}" "{probe}" %*\r\n@exit /b %errorlevel%\r\n',
        encoding="utf-8",
    )
    command = windows_hook_command(
        harness, "PreToolUse", "machine", resilient=harness == "cursor"
    )
    argv = command.split()
    if shell == "git-bash":
        git = shutil.which("git")
        bash = Path(git).resolve().parent.parent / "bin" / "bash.exe" if git else None
        if bash is None or not bash.is_file():
            pytest.skip("Git Bash is not installed on this Windows machine")
        argv = [str(bash), "--noprofile", "--norc", "-c", command]
    result = subprocess.run(
        argv,
        input='{"hook":"input"}',
        capture_output=True,
        text=True,
        cwd=project,
        env={
            **os.environ,
            "XDG_BIN_HOME": str(bin_dir),
            "YOKE_ROOT": str(project),
            "CLAUDE_PROJECT_DIR": str(project),
            "CURSOR_PROJECT_DIR": str(project),
        },
        check=False,
    )
    assert result.returncode == 7, result.stderr
    observed = json.loads(result.stdout)
    assert observed == {
        "root": str(project),
        "stdin": '{"hook":"input"}',
        "args": ["hook", "evaluate", "PreToolUse"],
    }
