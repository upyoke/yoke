"""Predictable non-login shell commands for native harness hooks."""

from __future__ import annotations

import base64
import os
import shlex
import shutil


_HOOK_PATH = (
    '"${XDG_BIN_HOME:-$HOME/.local/bin}:'
    '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"'
)


def hook_shell_command(body: str) -> str:
    """Wrap trusted hook source without reading operator startup files."""
    if "'" in body:
        raise ValueError("hook shell body cannot contain a single quote")
    return f"/bin/sh -c 'PATH={_HOOK_PATH}; export PATH; {body}'"


def windows_hook_command(
    harness_id: str, verb: str, config_owner: str | None, *, resilient: bool = False
) -> str:
    """Encode PowerShell source so cmd, PowerShell and Git Bash pass it intact."""
    root_var = {
        "claude-code": "CLAUDE_PROJECT_DIR",
        "codex": "YOKE_ROOT",
        "cursor": "CURSOR_PROJECT_DIR",
    }[harness_id]
    body = (
        "$ErrorActionPreference='Stop'; "
        "$bin=Join-Path $HOME '.local/bin'; "
        "if ($env:XDG_BIN_HOME) {$bin=$env:XDG_BIN_HOME}; "
        "$env:PATH=$bin+[IO.Path]::PathSeparator+$env:PATH; "
        f"$root=$env:{root_var}; if (!$root) {{$root=(Get-Location).Path}}; "
    )
    if resilient:
        body += (
            "$candidates=@($env:YOKE_ROOT,$env:CURSOR_PROJECT_DIR,"
            "(Get-Location).Path); $root=$null; "
            "foreach ($c in $candidates) {if ($c -and "
            "(Test-Path -LiteralPath $c -PathType Container)) {$root=$c; break}}; "
            "if (!$root) {foreach ($c in $candidates) {"
            r"$p=$c -replace '[\\/]\.(?:claude[\\/])?worktrees[\\/].*$',''; "
            "if ($p -and (Test-Path -LiteralPath $p -PathType Container)) "
            "{$root=$p; break}}}; "
            "if (!$root) {$root=$HOME}; Set-Location -LiteralPath $root; "
        )
    body += "$env:YOKE_ROOT=$root; "
    if harness_id != "claude-code":
        body += f"$env:YOKE_EXECUTOR='{harness_id}'; "
    if harness_id == "codex":
        body += "$env:YOKE_PROVIDER='openai'; "
    if config_owner:
        body += f"$env:YOKE_HOOK_CONFIG_OWNER='{config_owner}'; "
    body += f"& yoke hook evaluate {verb}; exit $LASTEXITCODE"
    encoded = base64.b64encode(body.encode("utf-16le")).decode("ascii")
    return (
        "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + encoded
    )


def hook_command_source(command: str) -> str:
    """Expose encoded source for ownership and diagnostics without executing it."""
    if " -EncodedCommand " in command:
        try:
            return base64.b64decode(command.rsplit(" ", 1)[1], validate=True).decode(
                "utf-16le"
            )
        except (ValueError, UnicodeError):
            return ""
    return command


def hook_command_for_os(command: str, windows: str) -> str:
    return windows if os.name == "nt" else command


def hook_command_start_problem(handler: dict, *, codex: bool = False) -> str:
    """Check the selected executable without running a policy hook as doctor."""
    command = handler.get("command", "")
    if codex and os.name == "nt":
        command = handler.get("commandWindows", command)
    try:
        argv = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        argv = []
    launcher = argv[0].strip('"') if argv else ""
    if launcher.lower() in {
        "echo",
        "cd",
        "set",
        "exit",
        "if",
        "for",
        "call",
        "type",
        "rem",
    }:
        return ""  # Shell builtins do not have an executable to locate.
    if (
        not launcher
        or (os.name == "nt" and launcher.startswith("/"))
        or not shutil.which(launcher)
    ):
        return (
            f"hook_command_unstartable: {launcher or 'empty command'} on {os.name}; "
            "run yoke project refresh and yoke setup; install the named shell if still missing"
        )
    return ""


__all__ = ["hook_shell_command"]
