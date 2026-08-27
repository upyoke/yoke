"""Prove, from this machine's own records, which sessions' natives are gone.

The control plane can only watch a session's heartbeat go quiet, and quiet
has two causes it cannot tell apart: an agent thinking for a long time, and
a process that died. So it waits out a TTL. The machine that started the
native does not have to guess — it kept the pid, and asking the local
process table whether that pid is still the process it recorded settles it.

Two record families name a session's process, both written by paths that
already exist for other reasons:

* the launch handle (``session-native-handles/<launch-id>.json``) the relay
  retains when a launched native registers, so termination can still reach
  a process containment has released;
* the process-anchor registry (``session-anchors/<anchor-pid>.json``) the
  hooks write to resolve ambient identity.

A record proves death only against itself: the recorded pid must still be
the recorded process, compared by start time so a reused pid reads as gone
rather than as alive. A session with no record at all proves nothing and is
left to the control plane's TTL sweep — this path only ever shortens the
wait for a death it can actually demonstrate.

A record whose process is gone is spent: it exists to reach a running
native, and it can never do that again. Once the report it fed has landed,
the record is removed — which is what the identity resolver already does
with a stale anchor it reads, and what keeps this sweep quiescent. Without
it, one death would be re-reported on every poll for the life of the
machine.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from yoke_cli.config import machine_config
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.session_control.function_ids import RELAY_LIVENESS_FUNCTION_ID
from yoke_contracts.session_identity import ANCHORS_DIR_NAME
from yoke_harness.session_relay_report_delivery import RELAY_REPORT_TIMEOUT_SECONDS
from yoke_harness.session_relay_termination import (
    NATIVE_HANDLE_DIRECTORY_NAME,
    local_state_root,
    read_local_record,
)


LAUNCH_HANDLE_SOURCE = "launch_handle"
PROCESS_ANCHOR_SOURCE = "process_anchor"
_LOGGER = logging.getLogger(__name__)

StartTimeOf = Callable[[int], str | None]


@dataclass(frozen=True)
class SessionProcessRecord:
    """One machine-local record naming the process behind a session."""

    session_id: str
    pid: int
    source: str
    running: bool
    path: Path


@dataclass(frozen=True)
class VerifiedDeadSession:
    """A session every one of whose recorded processes is gone."""

    session_id: str
    evidence: dict[str, Any]
    # Local paths, deliberately outside the reported evidence: the control
    # plane has no use for them, and they are pruned once the report lands.
    record_paths: tuple[Path, ...] = ()


def _anchors_directory(anchors_dir: Path | None) -> Path:
    return anchors_dir or (machine_config.yoke_home() / ANCHORS_DIR_NAME)


def _records_in(directory: Path) -> Iterator[tuple[Path, Mapping[str, Any]]]:
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        return
    for path in paths:
        record = read_local_record(path)
        if record is not None:
            yield path, record


def _observed(
    path: Path,
    session_id: Any,
    pid: Any,
    recorded_start: Any,
    source: str,
    start_time_of: StartTimeOf,
) -> SessionProcessRecord | None:
    session = str(session_id or "").strip()
    if not session or not isinstance(pid, int) or pid <= 0 or not recorded_start:
        return None
    return SessionProcessRecord(
        session_id=session,
        pid=pid,
        source=source,
        # A reused pid names a different process, so the native this record
        # was written for is gone either way.
        running=start_time_of(pid) == recorded_start,
        path=path,
    )


def session_process_records(
    *,
    state_dir: Path | None = None,
    anchors_dir: Path | None = None,
    start_time_of: StartTimeOf = process_start_time,
) -> tuple[SessionProcessRecord, ...]:
    """Read every machine-local record that names one session's process."""
    handles = local_state_root(state_dir) / NATIVE_HANDLE_DIRECTORY_NAME
    observed: list[SessionProcessRecord] = []
    for path, record in _records_in(handles):
        entry = _observed(
            path,
            record.get("target_session_id"),
            record.get("pid"),
            record.get("process_start_time"),
            LAUNCH_HANDLE_SOURCE,
            start_time_of,
        )
        if entry is not None:
            observed.append(entry)
    for path, record in _records_in(_anchors_directory(anchors_dir)):
        if record.get("shared_by_multiple_sessions"):
            # A pid hosting several conversations cannot name one session,
            # so it cannot testify about one session's death either.
            continue
        entry = _observed(
            path,
            record.get("session_id"),
            record.get("anchor_pid"),
            record.get("anchor_start_time"),
            PROCESS_ANCHOR_SOURCE,
            start_time_of,
        )
        if entry is not None:
            observed.append(entry)
    return tuple(observed)


def verified_dead_sessions(
    *,
    state_dir: Path | None = None,
    anchors_dir: Path | None = None,
    start_time_of: StartTimeOf = process_start_time,
) -> tuple[VerifiedDeadSession, ...]:
    """Return the sessions whose every recorded process is verifiably gone."""
    by_session: dict[str, list[SessionProcessRecord]] = {}
    for record in session_process_records(
        state_dir=state_dir,
        anchors_dir=anchors_dir,
        start_time_of=start_time_of,
    ):
        by_session.setdefault(record.session_id, []).append(record)
    dead: list[VerifiedDeadSession] = []
    for session_id, records in sorted(by_session.items()):
        if any(record.running for record in records):
            continue
        dead.append(
            VerifiedDeadSession(
                session_id,
                {
                    "records_considered": len(records),
                    "sources": sorted({record.source for record in records}),
                    "pids": sorted({record.pid for record in records}),
                },
                tuple(record.path for record in records),
            )
        )
    return tuple(dead)


def _prune(dead: tuple[VerifiedDeadSession, ...]) -> None:
    """Remove the spent records; a dead pid can never be reached again."""
    for entry in dead:
        for path in entry.record_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue


def report_verified_dead_sessions(
    dispatcher: Callable[..., Any],
    inventory: Any,
    *,
    state_dir: Path | None = None,
    anchors_dir: Path | None = None,
    timeout_s: int = RELAY_REPORT_TIMEOUT_SECONDS,
    start_time_of: StartTimeOf = process_start_time,
) -> tuple[str, ...]:
    """Report this machine's dead-process sessions and return those ended.

    The control plane decides: it ends only a reported session that belongs
    to this machine and is already past the stale TTL. A server that does
    not serve this function yet answers with a typed skew error, which is
    logged and skipped — the poll it rides along with keeps working.
    """
    dead = verified_dead_sessions(
        state_dir=state_dir,
        anchors_dir=anchors_dir,
        start_time_of=start_time_of,
    )
    if not dead:
        return ()
    response = dispatcher(
        function_id=RELAY_LIVENESS_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={
            "relay_id": inventory.relay_id,
            "machine_id": inventory.machine_id,
            "projects": list(inventory.project_ids),
            "sessions": [
                {"session_id": entry.session_id, "evidence": entry.evidence}
                for entry in dead
            ],
        },
        timeout_s=timeout_s,
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        _LOGGER.warning(
            "relay liveness report refused (%s): %s",
            getattr(error, "code", "relay_liveness_failed"),
            getattr(error, "message", ""),
        )
        # The records stay, so a server that starts serving this function
        # still hears about every death observed while it could not.
        return ()
    _prune(dead)
    ended = (getattr(response, "result", None) or {}).get("ended") or []
    return tuple(str(session_id) for session_id in ended)


__all__ = [
    "LAUNCH_HANDLE_SOURCE",
    "PROCESS_ANCHOR_SOURCE",
    "SessionProcessRecord",
    "VerifiedDeadSession",
    "report_verified_dead_sessions",
    "session_process_records",
    "verified_dead_sessions",
]
