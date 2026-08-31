"""Name what a silent watched gate is waiting on — and when to abort it.

A quiet heartbeat that only says "no child output" leaves an agent
choosing between waiting forever and killing a possibly-healthy run.
This module reads the same slot occupancy the admission loop publishes
plus the watched child's process tree, so a quiet period can report:

- nested admission deadlock (a descendant waiting on a slot this tree
  already holds — never recoverable; abort),
- a nested waiter on someone else's slot,
- a live child with no stdout,
- or silence with no descendants left to inspect.

Observability never raises: every probe degrades to an empty answer.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence

from yoke_core.domain.process_group_reaping import descendant_pids
from yoke_core.tools.gate_slot_observability import (
    SLOT_HELD_APP_PREFIX,
    SLOT_WAIT_APP_PREFIX,
    slot_parties,
)

#: Named reason stamped into the watcher capture when a nested waiter is
#: deadlocked behind a slot this run's own tree holds.
NESTED_ADMISSION_DEADLOCK = "nested_admission_deadlock"

_PID_IN_IDENTITY = re.compile(r"/pid(\d+)\s*$")

#: Disable the abort half (diagnosis still runs) — tests that need a
#: confirmed deadlock shape without reaping the fixture process tree.
STALL_ABORT_ENV = "YOKE_WATCH_STALL_ABORT"


@dataclass(frozen=True)
class StallReport:
    """One quiet-period diagnosis for a watched child."""

    waiting_on: str
    reason: Optional[str] = None
    abort: bool = False
    detail: str = ""

    def heartbeat_line(self, *, kind: str, quiet_seconds: float) -> str:
        """Render the progress/raw line a quiet watcher emits."""
        base = (
            f"# watch_{kind} still running; waiting on: {self.waiting_on}"
        )
        if self.detail:
            base = f"{base} ({self.detail})"
        return f"{base}; no child output for {quiet_seconds:g}s\n"

    def abort_line(self, *, kind: str) -> str:
        """Render the named abort banner written before the group is reaped."""
        reason = self.reason or NESTED_ADMISSION_DEADLOCK
        extra = f"; {self.detail}" if self.detail else ""
        return (
            f"# watch_{kind} aborted: {reason}{extra}; "
            "child process group reaped\n"
        )


def pid_from_slot_identity(identity: str) -> Optional[int]:
    """Parse the pid suffix from a slot identity, or None when absent."""
    match = _PID_IN_IDENTITY.search(identity)
    if match is None:
        return None
    return int(match.group(1))


def _ppid_map() -> dict[int, int]:
    try:
        listing = subprocess.run(
            ["ps", "-eo", "pid=,ppid="],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    mapping: dict[int, int] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        mapping[pid] = ppid
    return mapping


def ancestor_pids(pid: int, ppids: dict[int, int] | None = None) -> list[int]:
    """Return parent → … → near-root ancestors of *pid* (excluding *pid*)."""
    mapping = ppids if ppids is not None else _ppid_map()
    found: list[int] = []
    seen = {pid}
    current = mapping.get(pid)
    while current is not None and current not in seen and current > 0:
        found.append(current)
        seen.add(current)
        current = mapping.get(current)
    return found


def _command_for_pid(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip()


def _read_slot_parties() -> tuple[list[str], list[str]]:
    """Open a short-lived observer connection; empty on any failure."""
    try:
        from yoke_core.tools import gate_admission

        dsn = gate_admission._maintenance_dsn()
        if dsn is None:
            return ([], [])
        import psycopg

        with psycopg.connect(dsn, autocommit=True) as conn:
            return slot_parties(conn)
    except Exception:
        return ([], [])


def _identities_for_pids(
    identities: Sequence[str], pids: set[int]
) -> list[str]:
    matched: list[str] = []
    for identity in identities:
        parsed = pid_from_slot_identity(identity)
        if parsed is not None and parsed in pids:
            matched.append(identity)
    return matched


def stall_abort_enabled(env: dict[str, str] | None = None) -> bool:
    """Return whether a confirmed nested deadlock should reap the child."""
    raw = (env or os.environ).get(STALL_ABORT_ENV, "1")
    return raw.strip() not in {"0", "false", "False", "no", "NO"}


def diagnose_quiet_run(
    root_pid: int,
    *,
    holders: Sequence[str] | None = None,
    waiters: Sequence[str] | None = None,
    descendants: Sequence[int] | None = None,
    ancestors: Sequence[int] | None = None,
) -> StallReport:
    """Classify what a silent watched child is waiting on.

    *holders* / *waiters* / process-tree inputs are seams for unit tests;
    production callers leave them unset so this module probes live state.
    """
    if holders is None or waiters is None:
        live_holders, live_waiters = _read_slot_parties()
        if holders is None:
            holders = live_holders
        if waiters is None:
            waiters = live_waiters
    if descendants is None:
        descendants = descendant_pids(root_pid)
    if ancestors is None:
        ancestors = ancestor_pids(root_pid)

    holder_tree = {root_pid, *ancestors}
    descendant_set = set(descendants)
    nested_holders = _identities_for_pids(holders, holder_tree)
    nested_waiters = _identities_for_pids(waiters, descendant_set)

    if nested_holders and nested_waiters:
        detail = (
            f"holder={', '.join(nested_holders)}; "
            f"nested_waiter={', '.join(nested_waiters)}"
        )
        return StallReport(
            waiting_on="admission slot held by this run's own tree",
            reason=NESTED_ADMISSION_DEADLOCK,
            abort=stall_abort_enabled(),
            detail=detail,
        )

    if nested_waiters:
        who = ", ".join(holders) if holders else "an unnamed holder"
        return StallReport(
            waiting_on="admission slot",
            detail=(
                f"holders={who}; nested_waiter={', '.join(nested_waiters)}"
            ),
        )

    if holders and not nested_waiters and descendant_set:
        # A peer holds the machine slot while this tree is quiet — useful
        # context even when no descendant has stamped a wait marker yet.
        return StallReport(
            waiting_on="child process",
            detail=(
                f"gate slot held by {', '.join(holders)}; "
                f"descendants={len(descendant_set)}"
            ),
        )

    if descendants:
        sample_pid = descendants[-1]
        cmd = _command_for_pid(sample_pid)
        detail = f"pid={sample_pid}"
        if cmd:
            detail = f"{detail} cmd={cmd[:120]}"
        return StallReport(waiting_on="child process", detail=detail)

    return StallReport(waiting_on="no attributable child")


def handle_quiet_period(
    *,
    root_pid: int,
    kind: str,
    quiet_seconds: float,
    emit_immediate,
    write_raw,
    terminate_child,
    raw_capture,
    stall_abort_exit: int,
) -> Optional[int]:
    """Diagnose a quiet child; return an abort exit code or None to continue.

    *emit_immediate* writes a line to progress + stdout. *write_raw* appends
    to the forensic capture. *terminate_child* reaps the watched group.
    """
    report = diagnose_quiet_run(root_pid)
    heartbeat = report.heartbeat_line(kind=kind, quiet_seconds=quiet_seconds)
    emit_immediate(heartbeat)
    if not report.abort:
        return None
    abort_line = report.abort_line(kind=kind)
    write_raw(abort_line)
    emit_immediate(abort_line)
    terminate_child()
    emit_immediate(
        f"# watch_{kind} exit={stall_abort_exit} raw={raw_capture}\n"
    )
    return stall_abort_exit


__all__ = [
    "NESTED_ADMISSION_DEADLOCK",
    "STALL_ABORT_ENV",
    "StallReport",
    "ancestor_pids",
    "diagnose_quiet_run",
    "handle_quiet_period",
    "pid_from_slot_identity",
    "stall_abort_enabled",
    "SLOT_HELD_APP_PREFIX",
    "SLOT_WAIT_APP_PREFIX",
]
