"""Answer a relay pass's process identity questions from one portable snapshot.

Tokens use the same creation epochs as process_start_time. Missing PIDs are
checked live so a process started after the snapshot is never reported gone.
An unreadable snapshot falls back to the ordinary identity probe.
"""

from __future__ import annotations

from typing import Callable, Optional

from yoke_contracts import platform_process
from yoke_contracts.process_ancestry import process_start_time

StartTimeOf = Callable[[int], Optional[str]]


def _pid_exists(pid: int) -> bool:
    try:
        return platform_process.pid_alive(pid)
    except OSError:
        # Access refused: the pid exists, so ask it directly.
        return True


def process_start_reader() -> StartTimeOf:
    """Return creation-epoch tokens backed by one process-table snapshot."""
    try:
        table = {
            entry.pid: str(entry.start_time)
            for entry in platform_process.process_command_lines()
        }
    except OSError:
        return process_start_time
    if not table:
        return process_start_time

    def start_time_of(pid: int) -> Optional[str]:
        if pid in table:
            return table[pid]
        if pid <= 0 or not _pid_exists(pid):
            return None
        return process_start_time(pid)

    return start_time_of


__all__ = ["StartTimeOf", "process_start_reader"]
