"""Portable process-ancestry walk for session identity (shared contract).

Pure standard library (subprocess ``ps``; works on macOS and Linux). Both
sides of the ambient-identity contract walk the same body:

- **Anchor write (hook side):** a Yoke hook runs as a child of the
  per-session harness agent process, so :func:`find_nearest_harness_anchor`
  returns the first ancestor whose executable basename is in
  :data:`HARNESS_PROCESS_BASENAMES`.
- **Anchor read (shell side):** any Bash subshell the harness spawns shares
  that ancestor, so :func:`ancestor_pids` enumerates the candidate pids.

Lives in ``yoke-contracts`` so the product CLI client (which depends only
on this package) and the engine core resolve identity through one
implementation; ``yoke_core.domain.process_ancestry`` re-exports it.

The harness basename set is deliberately small: the per-session Claude agent
binary is ``.../claude-code/<version>/claude.app/Contents/MacOS/claude``
(basename ``claude``); the shared Claude Desktop shell (``Claude``) and its
helpers are intentionally NOT matched, so the nearest-first walk stops at
the per-session agent process and parallel sessions anchor to distinct pids.

Start times are opaque ``ps -o lstart=`` strings compared for equality
only — a recorded anchor whose pid was reused fails the comparison.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


HARNESS_PROCESS_BASENAMES = frozenset({"claude", "claude-code"})

_MAX_ANCESTOR_DEPTH = 64
_PS_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class ProcessAnchor:
    """One harness ancestor candidate: pid + reuse-defeating start time."""

    pid: int
    start_time: str
    process_name: str


def _ps_lines(args: List[str]) -> List[str]:
    """Run ``ps`` with ``args`` and return stdout lines; [] on any failure."""
    try:
        result = subprocess.run(
            ["ps", *args],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def parent_map() -> Dict[int, int]:
    """Return a ``pid -> ppid`` map for every live process (one ``ps`` call)."""
    parents: Dict[int, int] = {}
    for line in _ps_lines(["-axo", "pid=,ppid="]):
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            parents[int(fields[0])] = int(fields[1])
        except ValueError:
            continue
    return parents


def process_start_time(pid: int) -> Optional[str]:
    """Return the opaque ``ps -o lstart=`` string for ``pid`` or ``None``."""
    lines = _ps_lines(["-o", "lstart=", "-p", str(pid)])
    if not lines:
        return None
    value = lines[0].strip()
    return value or None


def process_command_name(pid: int) -> Optional[str]:
    """Return the executable basename for ``pid`` or ``None``.

    ``ps -o comm=`` yields the full executable path on macOS (which may
    contain spaces) and the bare command name on Linux; taking the whole
    line and basenaming it handles both.
    """
    lines = _ps_lines(["-o", "comm=", "-p", str(pid)])
    if not lines:
        return None
    raw = lines[0].strip()
    if not raw:
        return None
    return os.path.basename(raw)


def ancestor_pids(
    pid: Optional[int] = None,
    *,
    parents: Optional[Dict[int, int]] = None,
) -> List[int]:
    """Return ancestor pids of ``pid`` (nearest first, excluding ``pid``).

    Stops at pid 0/1, a missing parent entry, a cycle, or the depth cap.
    ``parents`` injects a process table for tests.
    """
    current = os.getpid() if pid is None else pid
    table = parent_map() if parents is None else parents
    seen = {current}
    chain: List[int] = []
    for _ in range(_MAX_ANCESTOR_DEPTH):
        parent = table.get(current)
        if parent is None or parent <= 1 or parent in seen:
            if parent == 1:
                chain.append(parent)
            break
        chain.append(parent)
        seen.add(parent)
        current = parent
    return chain


def is_harness_process_name(name: Optional[str]) -> bool:
    """True when ``name`` (an executable basename) is a known harness binary."""
    if not name:
        return False
    return name.lower() in HARNESS_PROCESS_BASENAMES


def find_nearest_harness_anchor(
    pid: Optional[int] = None,
    *,
    parents: Optional[Dict[int, int]] = None,
    name_of: Optional[Callable[[int], Optional[str]]] = None,
    start_time_of: Optional[Callable[[int], Optional[str]]] = None,
) -> Optional[ProcessAnchor]:
    """Return the nearest harness ancestor of ``pid`` (default: this process).

    Walks the parent chain nearest-first and returns the first ancestor
    whose executable basename matches :data:`HARNESS_PROCESS_BASENAMES`,
    with its live start time captured for pid-reuse defense. Returns
    ``None`` when no ancestor matches (e.g. an operator terminal not
    spawned by a harness).
    """
    resolve_name = process_command_name if name_of is None else name_of
    resolve_start = process_start_time if start_time_of is None else start_time_of
    for ancestor in ancestor_pids(pid, parents=parents):
        name = resolve_name(ancestor)
        basename = os.path.basename(name) if name else ""
        if not is_harness_process_name(basename):
            continue
        start_time = resolve_start(ancestor)
        if not start_time:
            return None
        return ProcessAnchor(
            pid=ancestor, start_time=start_time, process_name=basename,
        )
    return None


__all__ = [
    "HARNESS_PROCESS_BASENAMES",
    "ProcessAnchor",
    "ancestor_pids",
    "find_nearest_harness_anchor",
    "is_harness_process_name",
    "parent_map",
    "process_command_name",
    "process_start_time",
]
