"""Linux process facts from procfs, independent of procps and comm truncation."""

from __future__ import annotations

import os
import time
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
    """The established calendar start string, derived without ps; no zombies."""
    facts = _stat(pid)
    if facts is None or facts[1] == "Z":
        return None
    try:
        boot_time = next(
            int(line.split()[1])
            for line in (_PROC_ROOT / "stat").read_text().splitlines()
            if line.startswith("btime ")
        )
        started = boot_time + int(facts[2]) / os.sysconf("SC_CLK_TCK")
        return time.ctime(started)
    except (OSError, ValueError, IndexError, StopIteration, OverflowError):
        return None


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
