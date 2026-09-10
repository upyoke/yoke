"""Whether this machine is already running a native for one session.

A wake resumes a conversation by starting a process, so the question that
has to be settled before starting one is whether that conversation is
already executing. The control plane cannot settle it. It watches a
heartbeat and a tool-call clock, and a native between tool calls --
reasoning, streaming, or holding an armed wake subscription -- is silent on
both while being very much alive. Read as an absent hook route, that silence
resumed one session twice inside seventeen minutes: three natives under one
session id, interleaving tests, a commit, a rebase and lifecycle writes on
one worktree.

The machine that would start the second native does not have to infer
anything. It started the first one and kept the pid with the process start
time beside it, in two record families that already exist for other readers:

* the resume custody record the relay writes for every native it resumes,
  which is released only once that native has exited and its outcome has
  been reported;
* the launch handle the hook writes when a launched native registers.

Both are custody records: this machine started a headless native that exits
when its turn ends, so its pid still being that process means the turn is
still running. A record proves nothing about a pid it no longer names, so
the recorded start time is compared and a reused pid reads as gone.

The process-anchor registry is deliberately not read here. An anchor names a
process for any session, including an operator's own interactive one, where
a live process means a person has a window open rather than that a turn is
executing. Deferring on that would leave an idle interactive session's
envelope undelivered, so an operator-opened interactive session is outside
what this guard covers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT
from yoke_harness import session_launch_handles
from yoke_harness.session_launch_containment import supervised_records
from yoke_harness.session_relay_process_liveness import LAUNCH_HANDLE_SOURCE
from yoke_harness.session_relay_runtime import RelayAdapterResult, RelayExecutionContext
from yoke_harness.session_relay_termination import read_local_record


#: The relay's own record of a native it resumed, kept until that native
#: exits. Named beside the launch handle so a deferral says which custody
#: family answered.
RESUME_CUSTODY_SOURCE = "resume_custody"

StartTimeOf = Callable[[int], str | None]


@dataclass(frozen=True)
class RunningNative:
    """One native this machine started for a session and can still see."""

    session_id: str
    pid: int
    process_start_time: str
    source: str

    @property
    def evidence(self) -> dict[str, Any]:
        return {
            "result_code": NATIVE_TURN_RUNNING_RESULT,
            "running_native_pid": self.pid,
            "running_native_start_time": self.process_start_time,
            "running_native_source": self.source,
        }


@dataclass(frozen=True)
class FinishedResume:
    """A resume this machine started whose process is no longer that pid."""

    attempt_id: str
    pid: int
    process_start_time: str
    containment_reason: str = ""

    @property
    def evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pids": [self.pid],
            "process_start_times": {str(self.pid): self.process_start_time},
            "attempt_id": self.attempt_id,
        }
        if self.containment_reason:
            payload["containment_reason"] = self.containment_reason
        return payload


def _running(
    session_id: str,
    record: Mapping[str, Any],
    *,
    pid_key: str,
    source: str,
    start_time_of: StartTimeOf,
) -> RunningNative | None:
    pid = record.get(pid_key)
    recorded_start = record.get("process_start_time")
    if not isinstance(pid, int) or pid <= 0 or not recorded_start:
        return None
    if start_time_of(pid) != recorded_start:
        return None
    return RunningNative(session_id, pid, str(recorded_start), source)


def _launch_handles() -> Iterator[Mapping[str, Any]]:
    try:
        paths = sorted(session_launch_handles.native_handle_directory().glob("*.json"))
    except OSError:
        return
    for path in paths:
        record = read_local_record(path)
        if record is not None:
            yield record


def running_native_for_session(
    session_id: str | None,
    *,
    custody_state_dir: Path | None = None,
    start_time_of: StartTimeOf | None = None,
) -> RunningNative | None:
    """Return the native this machine still runs for ``session_id``, if any.

    The resume family is read first because it is the one that grows a
    record per wake: a session resumed twice has two, and the live one is
    what a third wake must see.

    ``start_time_of`` is resolved here rather than bound as a default, so
    the process table this reads is the one in force when it is called.
    """
    wanted = str(session_id or "").strip()
    if not wanted:
        return None
    start_time_of = start_time_of or process_start_time
    for _path, record in supervised_records(custody_state_dir):
        if str(record.get("supervision_kind") or "") != "resume":
            continue
        if str(record.get("native_session_id") or "").strip() != wanted:
            continue
        found = _running(
            wanted,
            record,
            pid_key="pid",
            source=RESUME_CUSTODY_SOURCE,
            start_time_of=start_time_of,
        )
        if found is not None:
            return found
    for record in _launch_handles():
        if str(record.get("target_session_id") or "").strip() != wanted:
            continue
        found = _running(
            wanted,
            record,
            pid_key="pid",
            source=LAUNCH_HANDLE_SOURCE,
            start_time_of=start_time_of,
        )
        if found is not None:
            return found
    return None


def finished_resume_for_session(
    session_id: str | None,
    *,
    custody_state_dir: Path | None = None,
    start_time_of: StartTimeOf | None = None,
) -> FinishedResume | None:
    """Return this session's dead resume custody, if any remain on disk."""
    wanted = str(session_id or "").strip()
    if not wanted:
        return None
    start_time_of = start_time_of or process_start_time
    for _path, record in supervised_records(custody_state_dir):
        if str(record.get("supervision_kind") or "") != "resume":
            continue
        if str(record.get("native_session_id") or "").strip() != wanted:
            continue
        pid = record.get("pid")
        recorded_start = record.get("process_start_time")
        if not isinstance(pid, int) or pid <= 0 or not recorded_start:
            continue
        if start_time_of(pid) == recorded_start:
            continue
        reason = record.get("containment_reason")
        return FinishedResume(
            str(record.get("launch_id") or ""),
            pid,
            str(recorded_start),
            str(reason).strip() if isinstance(reason, str) else "",
        )
    return None


def overlay_finished_resume_evidence(
    evidence: dict[str, Any],
    session_id: str,
    *,
    custody_state_dir: Path | None = None,
    start_time_of: StartTimeOf | None = None,
) -> str:
    """Prefer a dead resume's identity; return its attempt id when present."""
    finished = finished_resume_for_session(
        session_id,
        custody_state_dir=custody_state_dir,
        start_time_of=start_time_of,
    )
    if finished is None or not finished.attempt_id:
        return ""
    evidence.update(finished.evidence)
    return finished.attempt_id


def deferral_for_running_native(
    context: RelayExecutionContext,
    *,
    custody_state_dir: Path | None = None,
    start_time_of: StartTimeOf | None = None,
) -> RelayAdapterResult | None:
    """The outcome a wake takes instead of starting a second native.

    Returns ``None`` for every job that may proceed, so the shared runner
    asks one question and every surface adapter inherits the answer. The
    envelope is untouched: it stays pending for the live turn's own hook,
    and the control plane restores the wake budget this deferral did not
    spend.
    """
    if context.job_kind != "wake":
        return None
    running = running_native_for_session(
        context.target_session_id,
        custody_state_dir=custody_state_dir,
        start_time_of=start_time_of,
    )
    if running is None:
        return None
    return RelayAdapterResult(NATIVE_TURN_RUNNING_RESULT, evidence=running.evidence)


__all__ = [
    "FinishedResume",
    "RESUME_CUSTODY_SOURCE",
    "RunningNative",
    "deferral_for_running_native",
    "finished_resume_for_session",
    "overlay_finished_resume_evidence",
    "running_native_for_session",
]
