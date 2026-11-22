"""Predictable non-login shell commands for native harness hooks."""

from __future__ import annotations

import base64
import os
import re
import shlex
import shutil

from yoke_contracts.hook_runner.config_owner import CONFIG_OWNER_ENV_VAR


_HOOK_PATH = (
    '"${XDG_BIN_HOME:-$HOME/.local/bin}:'
    '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"'
)


def hook_shell_command(body: str) -> str:
    """Wrap trusted hook source without reading operator startup files."""
    if "'" in body:
        raise ValueError("hook shell body cannot contain a single quote")
    return f"/bin/sh -c 'PATH={_HOOK_PATH}; export PATH; {body}'"


#: ``yoke hook evaluate`` options that carry what a shell wrapper used to set.
HOOK_HARNESS_OPTION = "--harness"
HOOK_CONFIG_OWNER_OPTION = "--config-owner"

_OWNER = re.compile(
    rf"(?:{re.escape(CONFIG_OWNER_ENV_VAR)}=|{re.escape(HOOK_CONFIG_OWNER_OPTION)}\s+)"
    r"['\"]?([\w-]+)"
)


def windows_hook_command(harness_id: str, verb: str, config_owner: str | None) -> str:
    """One shell-neutral command line for every Windows hook shell.

    A bare ``yoke`` resolves ``yoke.cmd`` under cmd and PowerShell and the
    sibling ``/bin/sh`` shim under Git Bash; ``yoke hook evaluate`` itself
    sets the root, identity and owner context from these options.
    """
    command = f"yoke hook evaluate {verb} {HOOK_HARNESS_OPTION} {harness_id}"
    if config_owner:
        command += f" {HOOK_CONFIG_OWNER_OPTION} {config_owner}"
    return command


def hook_command_source(command: str) -> str:
    """Decode a retired PowerShell ``-EncodedCommand`` hook so refresh can replace it."""
    if " -EncodedCommand " in command:
        try:
            return base64.b64decode(command.rsplit(" ", 1)[1], validate=True).decode(
                "utf-16le"
            )
        except (ValueError, UnicodeError):
            return ""
    return command


def hook_command_owner(command: str) -> str | None:
    """The config owner a Yoke hook command carries, in any of its forms."""
    match = _OWNER.search(hook_command_source(command))
    return match.group(1) if match else None


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


__all__ = [
    "HOOK_CONFIG_OWNER_OPTION",
    "HOOK_HARNESS_OPTION",
    "hook_command_owner",
    "hook_command_source",
    "hook_shell_command",
    "windows_hook_command",
]
