"""Linux process facts from procfs, independent of procps and comm truncation."""

from __future__ import annotations

import os
from pathlib import Path

_PROC_ROOT = Path("/proc")


def _stat(pid: int) -> tuple[int, str, str] | None:
    """Read parent, state, and reuse-defeating start ticks from one stat record."""
    try:
        # The parenthesized comm may itself contain spaces or closing parens.
        fields = (_PROC_ROOT / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[1]), fields[0], fields[19]
    except (OSError, ValueError, IndexError):
        # Processes can disappear between enumerating a pid and reading it.
        return None


def process_command_name(pid: int) -> str | None:
    """Prefer the full argv[0], including titles used by pooled harness hosts."""
    directory = _PROC_ROOT / str(pid)
    try:
        name = os.fsdecode((directory / "cmdline").read_bytes().split(b"\0", 1)[0])
        if name:
            return os.path.basename(name)
    except OSError:
        pass
    try:
        return os.path.basename(os.readlink(directory / "exe")) or None
    except OSError:
        return None


def process_start_time(pid: int) -> str | None:
    """An opaque boot-relative start token; zombies answer as exited processes."""
    facts = _stat(pid)
    return f"proc:{facts[2]}" if facts and facts[1] != "Z" else None


def process_table() -> dict[int, tuple[int, str]]:
    """Return parent links and full names, tolerating process-exit races."""
    try:
        directories = list(_PROC_ROOT.iterdir())
    except OSError:
        return {}
    table = {}
    for directory in directories:
        if not directory.name.isdecimal():
            continue
        pid = int(directory.name)
        facts = _stat(pid)
        if facts is not None:
            table[pid] = (facts[0], process_command_name(pid) or "")
    return table
