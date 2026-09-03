"""Portable process-ancestry walk for session identity (shared contract).

Pure standard library (subprocess ``ps``; works on macOS and Linux). Both
sides of the ambient-identity contract walk the same body:

- **Anchor write (hook side):** a Yoke hook runs as a child of the
  per-session harness agent process, so :func:`find_nearest_harness_anchor`
  returns the first ancestor whose executable basename is in
  :data:`HARNESS_PROCESS_BASENAMES`.
- **Anchor read (shell side):** any Bash subshell the harness spawns shares
  that ancestor, so :func:`anchor_candidate_pids` enumerates the pids whose
  registry records may name this process's session.

Lives in ``yoke-contracts`` so the product CLI client (which depends only
on this package) and the engine core resolve identity through one
implementation.

The harness basename set is deliberately small: the per-session Claude agent
binary is ``.../claude-code/<version>/claude.app/Contents/MacOS/claude``
(basename ``claude``); the shared Claude Desktop shell (``Claude``) and its
helpers are intentionally NOT matched, so the nearest-first walk stops at
the per-session agent process and parallel sessions anchor to distinct pids.

A pid is only a usable anchor when it belongs to exactly one session. Some
harnesses host every concurrent conversation inside a single long-lived
process (:data:`MULTIPLEXED_PROCESS_BASENAMES`); such a pid is shared by
every sibling conversation, so anchoring to it would hand each one whichever
session id wrote the registry record last. Those processes are therefore
never valid anchors, and :func:`anchor_candidate_pids` — walked by the
write side and the read side alike — stops there rather than continuing to
an even more widely shared ancestor. Stopping matters most on the read
side: a multiplexed harness launched from an anchored one has a perfectly
good anchor two hops up naming a *different* session, and walking past the
shared host would resolve to it. Sessions under a multiplexing harness
identify themselves through the env chain, which that harness stamps per
conversation, or through a mapping its own hooks record
(:mod:`yoke_contracts.cursor_session_map`); ambient resolution failing
outright is the correct outcome when neither reached the process.

Start times are opaque ``ps -o lstart=`` strings compared for equality
only — a recorded anchor whose pid was reused fails the comparison.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple


HARNESS_PROCESS_BASENAMES = frozenset({"claude", "claude-code"})
#: The process title of a Claude daemon spare, which becomes one session's host.
CLAUDE_BACKGROUND_SPARE_PROCESS_NAME = "claude bg-spare"

MULTIPLEXED_PROCESS_BASENAMES = frozenset(
    {
        "codex",
        "codex-code-mode-host",
        "cursor",
        "cursor-agent",
        "claude bg-pty-host",
        CLAUDE_BACKGROUND_SPARE_PROCESS_NAME,
    }
)
"""Harness processes that host many concurrent sessions under one pid.

Never a valid anchor: every sibling conversation shares the pid, so a
record keyed on it resolves to whichever session wrote last. One
``cursor-agent`` process hosts the main conversation plus every subagent
session it spawns, and the Cursor IDE host process is shared the same way.

Claude's background-agent daemon keeps a pool of ``bg-pty-host`` and
``bg-spare`` processes and hands them to successive workers, so a pid
identifies the pool slot rather than any one session. They announce that
role in their process title, which is what ``ps`` reports as the command
name. Listing them matters most on the read side: their chain can rise
into an ordinary per-session ``claude``, and walking through would let a
worker resolve to -- and act as -- whichever session owns that process.
One such pid was observed holding a contention marker naming seven
sessions, which is that walk happening repeatedly on the write side.
"""

_MAX_ANCESTOR_DEPTH = 64
_PS_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class ProcessAnchor:
    """One harness ancestor candidate: pid + reuse-defeating start time."""

    pid: int
    start_time: str
    process_name: str


def ps_lines(args: List[str]) -> List[str]:
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


def process_table() -> Dict[int, Tuple[int, str]]:
    """Return ``pid -> (ppid, executable basename)`` for every live process.

    One ``ps`` call for both facts, so a walk that needs parents *and*
    names — every walk that must stop at a multiplexed host — costs no
    more process-table access than one that needs parents alone. ``comm``
    is requested last because it is the only column that can contain
    spaces (macOS reports a full path), which the bounded split keeps
    whole. A process reporting no command name maps to ``""`` rather than
    dropping out, so a missing name never breaks the parent chain.
    """
    table: Dict[int, Tuple[int, str]] = {}
    for line in ps_lines(["-axo", "pid=,ppid=,comm="]):
        fields = line.split(None, 2)
        if len(fields) < 2:
            continue
        try:
            pid, ppid = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        table[pid] = (ppid, os.path.basename(fields[2]) if len(fields) > 2 else "")
    return table


def parent_map() -> Dict[int, int]:
    """Return a ``pid -> ppid`` map for every live process (one ``ps`` call)."""
    return {pid: entry[0] for pid, entry in process_table().items()}


def process_start_time(pid: int) -> Optional[str]:
    """Return the opaque ``ps -o lstart=`` string for ``pid`` or ``None``."""
    lines = ps_lines(["-o", "lstart=", "-p", str(pid)])
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
    lines = ps_lines(["-o", "comm=", "-p", str(pid)])
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


def is_multiplexed_process_name(name: Optional[str]) -> bool:
    """True when ``name`` hosts many sessions under one pid (never an anchor)."""
    if not name:
        return False
    return name.lower() in MULTIPLEXED_PROCESS_BASENAMES


def _unknown_name(_pid: int) -> Optional[str]:
    return None


def anchor_candidate_pids(
    pid: Optional[int] = None,
    *,
    parents: Optional[Dict[int, int]] = None,
    name_of: Optional[Callable[[int], Optional[str]]] = None,
) -> List[int]:
    """Ancestors of ``pid``, nearest first, up to the first multiplexed host.

    The single expression of "which ancestors may carry this process's
    session identity". Both halves of the anchor contract walk it — the
    write side so it never records an anchor on a shared pid, and the read
    side so it never resolves *through* one to whatever harness session
    owns an ancestor above. Writing that rule once is the point: when only
    the write side enforced it, a session hosted by a multiplexed harness
    but launched from an anchored one resolved silently to the *launching*
    session, and acted with its authority.

    Both process-table facts come from one lookup when the caller injects
    neither. ``parents`` and ``name_of`` describe the same table, so
    injecting only ``parents`` describes a tree whose names are unknown and
    no ancestor is classified — reading live names against a synthetic tree
    would mix two process worlds and decide by coincidence.
    """
    resolve_name = name_of
    if resolve_name is None:
        if parents is None:
            table = process_table()
            parents = {ancestor: entry[0] for ancestor, entry in table.items()}
            resolve_name = {ancestor: entry[1] for ancestor, entry in table.items()}.get
        else:
            resolve_name = _unknown_name
    chain: List[int] = []
    for ancestor in ancestor_pids(pid, parents=parents):
        name = resolve_name(ancestor)
        if is_multiplexed_process_name(os.path.basename(name) if name else ""):
            break
        chain.append(ancestor)
    return chain


def find_nearest_harness_anchor(
    pid: Optional[int] = None,
    *,
    parents: Optional[Dict[int, int]] = None,
    name_of: Optional[Callable[[int], Optional[str]]] = None,
    start_time_of: Optional[Callable[[int], Optional[str]]] = None,
) -> Optional[ProcessAnchor]:
    """Return the nearest harness ancestor of ``pid`` (default: this process).

    Walks the anchor-candidate chain nearest-first and returns the first
    ancestor whose executable basename matches
    :data:`HARNESS_PROCESS_BASENAMES`, with its live start time captured
    for pid-reuse defense. Returns ``None`` when no candidate matches —
    an operator terminal not spawned by a harness, or a chain that ends at
    a multiplexed host before any per-session binary.
    """
    resolve_name = process_command_name if name_of is None else name_of
    resolve_start = process_start_time if start_time_of is None else start_time_of
    for ancestor in anchor_candidate_pids(
        pid,
        parents=parents,
        name_of=resolve_name,
    ):
        name = resolve_name(ancestor)
        basename = os.path.basename(name) if name else ""
        if not is_harness_process_name(basename):
            continue
        start_time = resolve_start(ancestor)
        if not start_time:
            return None
        return ProcessAnchor(
            pid=ancestor,
            start_time=start_time,
            process_name=basename,
        )
    return None


def find_nearest_named_process_anchor(
    process_names: Iterable[str],
    pid: Optional[int] = None,
    *,
    parents: Optional[Dict[int, int]] = None,
    name_of: Optional[Callable[[int], Optional[str]]] = None,
    start_time_of: Optional[Callable[[int], Optional[str]]] = None,
) -> Optional[ProcessAnchor]:
    """Return the nearest ancestor explicitly named by a surface contract.

    Unlike ambient identity, this walk may select a multiplexed host. Callers
    use the result only for process liveness; the anchor registry's tenancy
    marker still refuses a pid shared by multiple sessions.
    """
    targets = {os.path.basename(name).lower() for name in process_names if name}
    if not targets:
        return None
    resolve_name = name_of
    if resolve_name is None:
        if parents is None:
            table = process_table()
            parents = {process: entry[0] for process, entry in table.items()}
            resolve_name = {process: entry[1] for process, entry in table.items()}.get
        else:
            resolve_name = _unknown_name
    resolve_start = process_start_time if start_time_of is None else start_time_of
    for ancestor in ancestor_pids(pid, parents=parents):
        name = resolve_name(ancestor)
        basename = os.path.basename(name).lower() if name else ""
        if basename not in targets:
            continue
        start_time = resolve_start(ancestor)
        if not start_time:
            return None
        return ProcessAnchor(ancestor, start_time, basename)
    return None


__all__ = [
    "CLAUDE_BACKGROUND_SPARE_PROCESS_NAME",
    "HARNESS_PROCESS_BASENAMES",
    "MULTIPLEXED_PROCESS_BASENAMES",
    "ProcessAnchor",
    "anchor_candidate_pids",
    "ancestor_pids",
    "find_nearest_harness_anchor",
    "find_nearest_named_process_anchor",
    "is_harness_process_name",
    "is_multiplexed_process_name",
    "parent_map",
    "process_command_name",
    "process_start_time",
    "process_table",
    "ps_lines",
]
