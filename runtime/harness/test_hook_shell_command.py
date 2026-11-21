"""Non-login hook shell command coverage."""

from __future__ import annotations

import shlex
import os
import subprocess
from pathlib import Path

from yoke_contracts.hook_shell_command import hook_shell_command
import pytest


@pytest.mark.posix_only(reason='POSIX shell execution')
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


@pytest.mark.windows
def test_hook_shell_rejects_unquoted_source() -> None:
    try:
        hook_shell_command("printf 'unsafe'")
    except ValueError as exc:
        assert "single quote" in str(exc)
    else:
        raise AssertionError("single-quoted hook source was accepted")


@pytest.mark.windows
@pytest.mark.parametrize("harness", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("owner", [None, "machine"])
def test_windows_commands_are_bare_and_keep_the_posix_context(
    tmp_path, monkeypatch, harness, owner
):
    """The bare form sets what the POSIX ``env`` prefix sets, for every harness."""
    from yoke_cli.commands.adapters.hook_invocation_context import (
        apply_hook_invocation_context,
    )
    from yoke_contracts.hook_shell_command import (
        hook_command_owner,
        windows_hook_command,
    )
    from yoke_contracts.machine_hooks_render import evaluate_hook_command

    command = windows_hook_command(harness, "PreToolUse", owner)
    suffix = f" --config-owner {owner}" if owner else ""
    assert command == f"yoke hook evaluate PreToolUse --harness {harness}{suffix}"
    assert not any(mark in command for mark in ("powershell", "Encoded", "$", "|", "'"))
    argv = shlex.split(command)
    assert argv == command.split()

    posix = evaluate_hook_command(harness, "PreToolUse", config_owner=owner)
    expected = dict(
        pair.split("=", 1)
        for pair in posix.split(" env ", 1)[1].split(" yoke ", 1)[0].split()
    )
    expected["YOKE_ROOT"] = str(tmp_path)
    monkeypatch.chdir(tmp_path)
    environ = {"CLAUDE_PROJECT_DIR": str(tmp_path), "CURSOR_PROJECT_DIR": str(tmp_path)}
    apply_hook_invocation_context(
        argv[argv.index("--harness") + 1], argv[3], owner, environ
    )
    stamped = {k: v for k, v in environ.items() if k.startswith("YOKE_")}
    assert stamped == expected
    assert hook_command_owner(command) == hook_command_owner(posix) == owner


@pytest.mark.windows
@pytest.mark.parametrize("host_os", ["posix", "nt"])
def test_codex_renders_windows_command_and_hashes_the_selected_command(
    monkeypatch, host_os
):
    from yoke_contracts import codex_hook_trust as trust
    from yoke_contracts import hook_shell_command as shell
    from yoke_core.domain.agents_render_hooks import render_codex_hooks_block

    document = {"hooks": render_codex_hooks_block()}
    handler = document["hooks"]["Stop"][0]["hooks"][0]
    assert handler["command"].startswith("/bin/sh")
    assert handler["commandWindows"] == "yoke hook evaluate Stop --harness codex"
    monkeypatch.setattr(trust.os, "name", host_os)
    native_hash = trust.codex_hook_hashes_from_document(document)
    monkeypatch.setattr(trust.os, "name", "posix")
    posix_hash = trust.codex_hook_hashes_from_document(document)
    monkeypatch.setattr(trust.os, "name", "nt")
    windows_hash = trust.codex_hook_hashes_from_document(document)
    assert windows_hash != posix_hash
    assert native_hash == (windows_hash if host_os == "nt" else posix_hash)
    assert shell.hook_command_source(handler["commandWindows"]).startswith(
        "yoke hook evaluate Stop"
    )


@pytest.mark.windows
def test_doctor_selects_windows_command_and_names_missing_shell(monkeypatch):
    from yoke_contracts import hook_shell_command as shell

    monkeypatch.setattr(shell.os, "name", "nt")
    monkeypatch.setattr(
        shell.shutil, "which", lambda name: name if name == "yoke" else None
    )
    handler = {
        "command": "/bin/sh -c yoke",
        "commandWindows": shell.windows_hook_command("codex", "Stop", None),
    }
    assert shell.hook_command_start_problem(handler, codex=True) == ""
    assert "hook_command_unstartable" in shell.hook_command_start_problem(handler)


@pytest.mark.windows
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


@pytest.mark.windows
def test_windows_install_renders_linux_server_bundle_without_changing_policy(
    monkeypatch,
):
    import json
    from copy import deepcopy
    from yoke_cli.project_install import hook_platform
    from yoke_core.domain.install_bundle import _hooks_block
    from yoke_contracts.hook_shell_command import hook_command_owner

    bundle = {"hooks": _hooks_block(), "files": [{"path": "unchanged"}]}
    assert "commandWindows" not in json.dumps(bundle)  # The client composes it.
    owners = {
        "claude_settings_hooks": "claude",
        "codex_hooks": None,
        "cursor_hooks": "cursor-project",
    }
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
                    verb = old.get("hooks", [old])[0]["command"].split()[-1]
                    assert command.startswith(
                        f"yoke hook evaluate {verb.strip(chr(39))} --harness "
                    )
                    assert "powershell" not in command
                    assert hook_command_owner(command) == owners[key]


@pytest.mark.windows
def test_refresh_replaces_codex_entry_when_only_windows_command_changes(tmp_path):
    import json
    from copy import deepcopy
    from yoke_cli.project_install import hooks
    from yoke_contracts.project_contract.hook_entries import provided_records

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


@pytest.mark.windows
@pytest.mark.windows_only(reason="executes native Windows hook shells")
@pytest.mark.parametrize("harness", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("shell", ["cmd", "powershell", "git-bash"])
def test_native_windows_command_keeps_stdin_args_and_exit_status(
    tmp_path, harness, shell
):
    """The exact rendered text resolves the bin shim in every hook shell."""
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
        "import json, sys\n"
        "print(json.dumps({'stdin': sys.stdin.read(), 'args': sys.argv[1:]}))\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )
    (bin_dir / "yoke.cmd").write_text(
        f'@"{sys.executable}" "{probe}" %*\r\n@exit /b %errorlevel%\r\n',
        encoding="utf-8",
    )
    (bin_dir / "yoke").write_text(
        f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "{probe.as_posix()}" "$@"\n',
        encoding="utf-8",
    )
    command = windows_hook_command(harness, "PreToolUse", "machine")
    if shell == "cmd":
        argv = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command]
    elif shell == "powershell":
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        git = shutil.which("git")
        configured = os.environ.get("YOKE_CI_GIT_BASH")
        candidates = [Path(configured)] if configured else [
            root / "bin" / "bash.exe" for root in Path(git).resolve().parents
        ] if git else []
        bash = next((path for path in candidates if path.is_file()), None)
        assert bash is not None, "Install Git for Windows with Git Bash"
        argv = [str(bash), "--noprofile", "--norc", "-c", command]
    result = subprocess.run(
        argv,
        input='{"hook":"input"}',
        capture_output=True,
        text=True,
        cwd=project,
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        check=False,
    )
    assert result.returncode == 7, result.stderr
    assert json.loads(result.stdout) == {
        "stdin": '{"hook":"input"}',
        "args": command.split()[1:],
    }


def test_tracked_project_hooks_stay_posix_while_machine_hooks_go_native(monkeypatch):
    """Decision 15934: tracked repo hook files never depend on the host OS."""
    from yoke_contracts import hook_shell_command as shell_os
    from yoke_contracts.harness_machine_hooks import machine_hooks_for_harness
    from yoke_contracts.machine_hooks_render import render_user_hook_entries
    from yoke_core.domain import agents_render_hooks

    def project_commands():
        return (
            agents_render_hooks._claude_command("Stop"),
            agents_render_hooks._cursor_command("Stop"),
            agents_render_hooks._cursor_command("PreToolUse"),
        )

    posix = project_commands()
    monkeypatch.setattr(shell_os.os, "name", "nt")
    assert project_commands() == posix
    assert all(" -EncodedCommand " not in command for command in posix)
    for harness in ("claude-code", "cursor"):
        entries = render_user_hook_entries(machine_hooks_for_harness(harness))
        commands = [
            handler["command"]
            for event_entries in entries.values()
            for entry in event_entries
            for handler in entry.get("hooks", [entry])
        ]
        assert commands and all(
            c.startswith("yoke hook evaluate ") and f"--harness {harness}" in c
            for c in commands
        )
