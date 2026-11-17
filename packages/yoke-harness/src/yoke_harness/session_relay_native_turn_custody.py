"""Whether this machine is already running a native for one session.

A wake resumes a conversation by starting a process, so first it must be
settled whether that conversation is already executing. The control plane
cannot settle it: a native between tool calls is silent on its heartbeat
and tool-call clock while very much alive. Read as an absent hook route,
that silence once resumed one session twice in seventeen minutes, three
natives interleaving work on one worktree.

The machine that would start the second native started the first and kept
its pid and process start time, in the resume custody record the relay
writes for every native it resumes (released only after that native exits
and its outcome is reported) and in the launch handle the hook writes when
a launched native registers. While that pid is still that process the
session is that native's, mid-turn or past a turn that left a background
command running, so a resume would be a second native either way. A record
proves nothing about a pid it no longer names, so the start time is
compared and a reused pid reads as gone. The supervisor's recorded exit, or
a containment result that proved the exit, settles it first: a command the
turn left in its process group is not a turn, and reading it as one held a
gone Cursor worker's next message until steering terminated the session.

A deferral also reports how long the native has been silent, from its own
capture, and the shell commands still running under it
(:mod:`yoke_harness.session_relay_native_background`). Neither changes the
refusal -- silence is never authority to start a second turn, and a recorded
park declares a wait, not a process exit. They travel because the refusal
repeats: natives held custody for an hour while every wake was declined and
nothing said whether the turn was moving. The report reads them against the
session's turn posture to say whether a turn is running or has ended and a
background command is holding the process.
"""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass, replace
from pathlib import Path
import time
from typing import Any, Callable, Iterator, Mapping

from yoke_contracts.process_ancestry import process_start_time
from yoke_harness.session_process_custody import SUCCESS_RESULTS, custody_state
from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT
from yoke_harness.session_relay_native_background import (
    BackgroundChild,
    background_children,
    background_evidence,
)
from yoke_harness.session_relay_native_capture_format import (
    NativeCapture,
    parse_capture,
)
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
ChildrenOf = Callable[[int], tuple[BackgroundChild, ...]]


@dataclass(frozen=True)
class RunningNative:
    """One native this machine started for a session and can still see."""

    session_id: str
    pid: int
    process_start_time: str
    source: str
    #: Seconds since this native last said anything, when its capture records
    #: that. ``None`` when there is no capture to read or it predates the
    #: field -- an unknown silence is reported as unknown rather than as zero.
    silent_for_seconds: int | None = None
    #: Shell commands under that pid; after an ended turn, the native's hold.
    background_children: tuple[BackgroundChild, ...] = ()

    @property
    def evidence(self) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "result_code": NATIVE_TURN_RUNNING_RESULT,
            "running_native_pid": self.pid,
            "running_native_start_time": self.process_start_time,
            "running_native_source": self.source,
        }
        if self.silent_for_seconds is not None:
            evidence["running_native_silent_for_seconds"] = self.silent_for_seconds
        evidence.update(background_evidence(self.background_children))
        return evidence


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


def _capture(record: Mapping[str, Any]) -> NativeCapture | None:
    raw = record.get("capture_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return parse_capture(Path(raw).read_bytes())
    except OSError:
        return None


def _turn_running(record: Mapping[str, Any], start_time_of: StartTimeOf) -> bool:
    """A recorded exit ends the turn; otherwise the process identity decides."""
    if record.get("containment_result") in SUCCESS_RESULTS:
        return False
    capture = _capture(record)
    if capture is not None and capture.exited:
        return False
    if record.get("process_members"):
        return custody_state(record) != "gone"
    return start_time_of(int(record["pid"])) == record.get("process_start_time")


def _silent_for_seconds(
    capture: NativeCapture | None, *, now: Callable[[], float]
) -> int | None:
    """How long this native has produced nothing, from its own capture.

    The capture's modification time cannot answer this: the supervisor
    refreshes a running capture on a fixed interval so that a reader can tell
    a live supervisor from a dead one, so that clock reports the supervisor.
    ``last-output-at`` inside the envelope is the native's own, and its
    absence -- no capture, an unreadable one, or one written before the field
    existed -- is reported as unknown rather than guessed at.
    """
    spoke = capture.last_output_at if capture is not None else None
    if spoke is None:
        return None
    current = datetime.fromtimestamp(now(), timezone.utc)
    return max(0, int((current - spoke).total_seconds()))


def _running(
    session_id: str,
    record: Mapping[str, Any],
    *,
    pid_key: str,
    source: str,
    start_time_of: StartTimeOf,
    now: Callable[[], float] = time.time,
) -> RunningNative | None:
    pid = record.get(pid_key)
    recorded_start = record.get("process_start_time")
    if not isinstance(pid, int) or pid <= 0 or not recorded_start:
        return None
    if not _turn_running(record, start_time_of):
        return None
    return RunningNative(
        session_id,
        pid,
        str(recorded_start),
        source,
        silent_for_seconds=_silent_for_seconds(_capture(record), now=now),
    )


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
        if wanted not in {
            str(record.get("native_session_id") or "").strip(),
            str(record.get("target_session_id") or "").strip(),
        }:
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
    for _path, record in sorted(
        supervised_records(custody_state_dir),
        key=lambda entry: int(entry[1].get("recorded_at") or 0),
        reverse=True,
    ):
        if str(record.get("supervision_kind") or "") != "resume":
            continue
        if wanted not in {
            str(record.get("native_session_id") or "").strip(),
            str(record.get("target_session_id") or "").strip(),
        }:
            continue
        pid = record.get("pid")
        recorded_start = record.get("process_start_time")
        if not isinstance(pid, int) or pid <= 0 or not recorded_start:
            continue
        if _turn_running(record, start_time_of):
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
    children_of: ChildrenOf = background_children,
) -> RelayAdapterResult | None:
    """The outcome a wake takes instead of starting a second native.

    Returns ``None`` for every job that may proceed, so the shared runner
    asks one question and every surface adapter inherits the answer. A
    parked session is held while its native is still that process: only
    an observed exit or proven process absence permits another resume.
    The envelope is untouched when this does defer: it
    stays pending for the live turn's own hook, and the control plane
    restores the wake budget this deferral did not spend.
    """
    if context.job_kind != "wake":
        return None
    running = running_native_for_session(
        context.target_session_id,
        custody_state_dir=custody_state_dir,
        start_time_of=start_time_of,
    )
    if running is None:
        from yoke_harness.session_relay_interactive_holder import interactive_holder

        running = interactive_holder(
            context, custody_state_dir=custody_state_dir, start_time_of=start_time_of,
        )
    if running is None:
        return None
    running = replace(running, background_children=children_of(running.pid))
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
