"""The background commands keeping a headless native alive after its turn.

A Claude native runs with no background-wait ceiling (see
:mod:`yoke_harness.session_relay_claude_native`), so a turn that leaves a
background command running ends without the process exiting. When that
command returns, the native takes another turn, and that turn's hooks
deliver whatever is waiting. Custody still holds the wake, because that
process is still the session. The seat needs to know which command it is
waiting on: ending that command makes the native take its next turn.

A tool command runs under a shell, so a shell child of the native is one of
those commands. Its other children, such as MCP servers, belong to the
native itself and are not named. Each command is named by the first
non-shell process under its shell: ``npm run build``, not the shell
wrapper that started it. A shell with nothing under it is named by itself.
A name carries only the program and its leading plain words, never options
or credential-shaped arguments.

Whether those children are background commands or the current tool call is
not decided here: only the control plane's turn posture says if the turn
has ended. This module only lists the children.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath, PureWindowsPath
from typing import Any, Iterable

from yoke_contracts import platform_process
from yoke_contracts.platform_process import ProcessInfo
from yoke_contracts.self_host_bootstrap_output import redact_api_tokens

SHELL_BASENAMES = frozenset(
    {"sh", "bash", "zsh", "dash", "fish", "ksh", "pwsh", "powershell", "cmd"}
)
#: Attempt evidence keeps text fields to 128 characters. Only the first
#: command and the count travel; the first one is the seat's lever either way.
COMMAND_LIMIT = 128
_WORD_COUNT = 4
_WORD_LIMIT = 40
_PLAIN_WORD = re.compile(r"[A-Za-z0-9._/,+]+")
_MAX_DEPTH = 8


@dataclass(frozen=True)
class BackgroundChild:
    """One command the native started and is still waiting on."""

    pid: int
    command: str


def _is_shell(entry: ProcessInfo) -> bool:
    name = PureWindowsPath(PurePath(entry.name).name).name.lower().lstrip("-")
    return name.removesuffix(".exe") in SHELL_BASENAMES


def _plain(word: str) -> bool:
    return bool(_PLAIN_WORD.fullmatch(word)) and len(word) <= _WORD_LIMIT


def _command(entry: ProcessInfo) -> str:
    """The program and its leading plain words: ``npm run build``.

    A command line can carry credentials in options or arguments, and this
    text leaves the machine. So naming stops at the first option, or at any
    word that is long or carries ``=``, ``:`` or ``@``. That is enough to
    recognise the command, and its pid is what the seat acts on.
    """
    argv = entry.cmdline or (entry.name,)
    words = [PureWindowsPath(PurePath(argv[0]).name).name]
    for word in argv[1:]:
        if len(words) > _WORD_COUNT or word.startswith("-") or not _plain(word):
            break
        words.append(word)
    return redact_api_tokens(" ".join(words))[:COMMAND_LIMIT]


def _named_under(
    shell: ProcessInfo, by_parent: dict[int, list[ProcessInfo]]
) -> ProcessInfo:
    current = shell
    for _ in range(_MAX_DEPTH):
        below = sorted(by_parent.get(current.pid, ()), key=lambda e: e.pid)
        if not below:
            return current
        current = below[0]
        if not _is_shell(current):
            return current
    return current


def background_children(
    pid: int, processes: Iterable[ProcessInfo] | None = None
) -> tuple[BackgroundChild, ...]:
    """Name the shell commands running under native ``pid``, oldest pid first.

    An unreadable process table names nothing. That is reported as no
    children rather than raised, because custody still holds the wake on
    the pid alone.
    """
    try:
        table = list(
            processes if processes is not None
            else platform_process.process_command_lines()
        )
    except OSError:
        return ()
    by_parent: dict[int, list[ProcessInfo]] = defaultdict(list)
    for entry in table:
        by_parent[entry.ppid].append(entry)
    found: list[BackgroundChild] = []
    for child in sorted(by_parent.get(pid, ()), key=lambda e: e.pid):
        if not _is_shell(child):
            continue
        named = _named_under(child, by_parent)
        found.append(BackgroundChild(named.pid, _command(named)))
    return tuple(found)


def background_evidence(children: tuple[BackgroundChild, ...]) -> dict[str, Any]:
    """Flat attempt-evidence fields naming the first command and the count."""
    if not children:
        return {}
    return {
        "running_native_background_pid": children[0].pid,
        "running_native_background_command": children[0].command,
        "running_native_background_count": len(children),
    }


__all__ = [
    "BackgroundChild",
    "COMMAND_LIMIT",
    "SHELL_BASENAMES",
    "background_children",
    "background_evidence",
]
