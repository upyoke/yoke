"""Answer many process start-time questions from one process-table read.

A relay pass checks every custody record on the machine against the process
that record names. On ``ps`` platforms each :func:`process_start_time` call is
a subprocess, so a machine holding a thousand records spent most of a minute
per poll spawning ``ps``. The poll's next claim waited out that whole pass, so
wakes for different sessions ran one after another instead of in parallel.

:func:`process_start_reader` reads the table once and answers each pid from
it with the same token :func:`process_start_time` returns. A pid missing from
the snapshot is either gone or started after the read: an in-process
liveness check tells those apart without a subprocess; a pid that exists is asked
directly, so a process recorded after the snapshot never reads as gone. A
table that could not be read answers every pid directly. Linux and Windows
already read start times in-process and keep the per-pid reader.
"""

from __future__ import annotations

import sys
from typing import Callable, Dict, Optional

from yoke_contracts import platform_process
from yoke_contracts.process_ancestry import process_start_time, ps_lines

#: A process that exited unreaped; it answers as gone, as in process_start_time.
_DEFUNCT_PROCESS_STATE = "Z"

StartTimeOf = Callable[[int], Optional[str]]


def _start_time_table() -> Dict[int, Optional[str]]:
    """Return ``pid -> start token`` (None for zombies) from one ``ps`` call."""
    table: Dict[int, Optional[str]] = {}
    for line in ps_lines(["-axo", "pid=,stat=,lstart="]):
        fields = line.strip().split(None, 2)
        if len(fields) < 3:
            continue
        try:
            pid = int(fields[0])
        except ValueError:
            continue
        defunct = fields[1].startswith(_DEFUNCT_PROCESS_STATE)
        table[pid] = None if defunct else (fields[2].strip() or None)
    return table


def _pid_exists(pid: int) -> bool:
    try:
        return platform_process.pid_alive(pid)
    except OSError:
        # Access refused: the pid exists, so ask it directly.
        return True


def process_start_reader() -> StartTimeOf:
    """Return a start-time reader backed by one process-table snapshot."""
    if sys.platform in {"linux", "win32"}:
        return process_start_time
    table = _start_time_table()
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
