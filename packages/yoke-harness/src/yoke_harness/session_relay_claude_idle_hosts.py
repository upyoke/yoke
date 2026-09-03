"""Reclaim the Claude background hosts that ended sessions leave behind.

Every Claude session launched on this machine runs inside a ``claude
bg-spare`` process the Claude daemon handed it. When the Yoke session ends,
nothing tells the daemon: the background job stays open and idle, so its
process — around half a gigabyte resident — outlives the work by days. Ten
such hosts once held 2.1 GB on a machine with 44 MB free.

Two rules, both Claude-specific because the daemon, its job registry, and
the spare pool are Claude Code runtime facts with no Codex or Cursor
counterpart:

* An idle host whose Yoke session has ended is stopped through Claude Code's
  own stop path, which closes the job and lets the daemon release the
  process. A plain signal is never sent to a host Claude Code still tracks:
  the daemon reads that as a crash and auto-restarts the session, which is
  how a week-old worker once came back to replay a finished report.
* A host whose job Claude Code already reports ``stopped`` and that still
  lingers is signalled directly, SIGTERM then SIGKILL.

A host is idle only when its process has no children, Claude's own job
record has not moved for :data:`IDLE_HOST_THRESHOLD_SECONDS`, and the job
is not mid-turn. The newest spare is always left alone: it is the daemon's
warm pool. A spare Claude has no session record for is likewise untouched.

The control plane answers which sessions have ended; this machine never
guesses from a quiet row. Every host stopped or signalled is reported back
with its pid, age, and resident size, so the steering report can show what
was reclaimed. A control plane that does not serve the function yet answers
with a typed skew error, logged and skipped, and the poll it rides on keeps
working.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import signal
import time
from typing import Any, Callable, Mapping

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.process_ancestry import (
    CLAUDE_BACKGROUND_SPARE_PROCESS_NAME,
    process_start_time,
    ps_lines,
)
from yoke_contracts.session_control.function_ids import RELAY_IDLE_HOSTS_FUNCTION_ID
from yoke_harness.claude_runtime_records import (
    claude_job_state,
    claude_session_record,
)
from yoke_harness.session_relay_report_delivery import RELAY_REPORT_TIMEOUT_SECONDS
from yoke_harness.session_relay_termination import (
    TERMINATE_WAIT_SECONDS,
    stop_claude_background_agent,
)


#: How long a childless host's job record must stay untouched before the
#: host counts as idle. Long enough that a worker between two tool calls,
#: or a session sleeping through a transient end, is never reclaimed.
IDLE_HOST_THRESHOLD_SECONDS = 600

STOP_JOB_ACTION = "stopped_job"
SIGNAL_HOST_ACTION = "signalled_host"
#: The Claude job state that means the daemon no longer tracks the host.
CLAUDE_JOB_EXITED_STATE = "stopped"
#: The Claude job tempo that means a turn is in progress.
CLAUDE_JOB_ACTIVE_TEMPO = "active"
#: The Claude session kind of a daemon-hosted background job.
CLAUDE_BACKGROUND_SESSION_KIND = "bg"
# A session record written this many seconds before its process started
# still names that process: the two clocks are stamped by different writers.
_RECORD_START_SLACK_SECONDS = 5
_PS_START_FORMAT = "%a %b %d %H:%M:%S %Y"
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostProcess:
    """One live process as ``ps`` reports it, with its start as an epoch."""

    pid: int
    ppid: int
    name: str
    start_epoch: float
    rss_kb: int


@dataclass(frozen=True)
class IdleHost:
    """One childless spare whose job record has been still past the threshold."""

    pid: int
    session_id: str
    job_id: str
    job_state: str
    start_epoch: float
    age_seconds: int
    idle_seconds: int
    rss_kb: int
    exited: bool

    def evidence(self, action: str, result: str) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "pid": self.pid,
            "action": action,
            "result": result,
            "job_state": self.job_state,
            "age_seconds": self.age_seconds,
            "idle_seconds": self.idle_seconds,
            "rss_kb": self.rss_kb,
        }


def start_epoch(lstart: str | None) -> float | None:
    """Parse a ``ps -o lstart`` stamp into a local epoch, or nothing."""
    if not lstart:
        return None
    try:
        return time.mktime(time.strptime(lstart.strip(), _PS_START_FORMAT))
    except ValueError:
        return None


def process_inventory() -> dict[int, HostProcess]:
    """Return every live process with parent, title, start, and resident size."""
    table: dict[int, HostProcess] = {}
    for line in ps_lines(["-axo", "pid=,ppid=,rss=,lstart=,comm="]):
        fields = line.split(None, 8)
        if len(fields) < 9:
            continue
        started = start_epoch(" ".join(fields[3:8]))
        try:
            pid, ppid, rss = int(fields[0]), int(fields[1]), int(fields[2])
        except ValueError:
            continue
        if started is None:
            continue
        table[pid] = HostProcess(pid, ppid, fields[8].strip(), started, rss)
    return table


def plan_idle_hosts(
    processes: Mapping[int, HostProcess],
    *,
    now: float,
    session_record_of: Callable[
        [int], Mapping[str, Any] | None
    ] = claude_session_record,
    job_state_of: Callable[[str], Mapping[str, Any] | None] = claude_job_state,
) -> tuple[IdleHost, ...]:
    """Name every spare that is idle and provably one session's used host."""
    spares = [
        entry
        for entry in processes.values()
        if entry.name == CLAUDE_BACKGROUND_SPARE_PROCESS_NAME
    ]
    if not spares:
        return ()
    newest = max(spares, key=lambda entry: entry.start_epoch).pid
    parents = {entry.ppid for entry in processes.values()}
    hosts: list[IdleHost] = []
    for spare in sorted(spares, key=lambda entry: entry.pid):
        if spare.pid == newest or spare.pid in parents:
            continue
        record = session_record_of(spare.pid)
        if record is None or record.get("kind") != CLAUDE_BACKGROUND_SESSION_KIND:
            continue
        session_id = str(record.get("session_id") or "")
        started = record.get("started_epoch")
        # A record older than the process names a pid the daemon reused.
        if not session_id or not isinstance(started, (int, float)):
            continue
        if started + _RECORD_START_SLACK_SECONDS < spare.start_epoch:
            continue
        job_id = str(record.get("job_id") or "")
        job = job_state_of(job_id) if job_id else None
        if job is None or job.get("tempo") == CLAUDE_JOB_ACTIVE_TEMPO:
            continue
        updated = job.get("updated_epoch")
        if not isinstance(updated, (int, float)):
            continue
        idle_seconds = int(now - updated)
        if idle_seconds < IDLE_HOST_THRESHOLD_SECONDS:
            continue
        state = str(job.get("state") or "")
        hosts.append(
            IdleHost(
                pid=spare.pid,
                session_id=session_id,
                job_id=job_id,
                job_state=state,
                start_epoch=spare.start_epoch,
                age_seconds=int(now - spare.start_epoch),
                idle_seconds=idle_seconds,
                rss_kb=spare.rss_kb,
                exited=state == CLAUDE_JOB_EXITED_STATE,
            )
        )
    return tuple(hosts)


def signal_exited_host(host: IdleHost) -> str:
    """SIGTERM, then SIGKILL, the one process the host record still names."""
    if start_epoch(process_start_time(host.pid)) != host.start_epoch:
        return "already_exited"
    try:
        os.kill(host.pid, signal.SIGTERM)
    except OSError:
        return "already_exited"
    deadline = time.monotonic() + TERMINATE_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            os.kill(host.pid, 0)
        except OSError:
            return "terminated"
        time.sleep(0.1)
    try:
        os.kill(host.pid, signal.SIGKILL)
    except OSError:
        return "terminated"
    return "killed"


def _report(
    dispatcher: Callable[..., Any],
    inventory: Any,
    *,
    hosts: list[dict[str, Any]],
    reclaimed: list[dict[str, Any]],
    timeout_s: int,
) -> tuple[str, ...] | None:
    response = dispatcher(
        function_id=RELAY_IDLE_HOSTS_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={
            "relay_id": inventory.relay_id,
            "machine_id": inventory.machine_id,
            "projects": list(inventory.project_ids),
            "hosts": hosts,
            "reclaimed": reclaimed,
        },
        timeout_s=timeout_s,
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        _LOGGER.warning(
            "relay idle-host report refused (%s): %s",
            getattr(error, "code", "relay_idle_hosts_failed"),
            getattr(error, "message", ""),
        )
        return None
    ended = (getattr(response, "result", None) or {}).get("ended") or []
    return tuple(str(session_id) for session_id in ended)


def reclaim_idle_claude_hosts(
    dispatcher: Callable[..., Any],
    inventory: Any,
    *,
    processes: Mapping[int, HostProcess] | None = None,
    now: float | None = None,
    session_record_of: Callable[
        [int], Mapping[str, Any] | None
    ] = claude_session_record,
    job_state_of: Callable[[str], Mapping[str, Any] | None] = claude_job_state,
    signal_host: Callable[[IdleHost], str] = signal_exited_host,
    stop_job: Callable[[str], tuple[str, dict[str, object]]] = (
        stop_claude_background_agent
    ),
    timeout_s: int = RELAY_REPORT_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], ...]:
    """Stop or signal this machine's idle Claude hosts; return what was reclaimed.

    Hosts Claude already reports exited are signalled locally. The rest are
    put to the control plane, which answers with the ones whose Yoke session
    has ended; those are stopped through Claude's own stop path and reported
    on a second call so the evidence lands the same cycle it was produced.
    """
    hosts = plan_idle_hosts(
        processes if processes is not None else process_inventory(),
        now=time.time() if now is None else now,
        session_record_of=session_record_of,
        job_state_of=job_state_of,
    )
    if not hosts:
        return ()
    reclaimed = [
        host.evidence(SIGNAL_HOST_ACTION, signal_host(host))
        for host in hosts
        if host.exited
    ]
    open_hosts = [host for host in hosts if not host.exited]
    ended = _report(
        dispatcher,
        inventory,
        hosts=[{"session_id": host.session_id, "pid": host.pid} for host in open_hosts],
        reclaimed=reclaimed,
        timeout_s=timeout_s,
    )
    stopped: list[dict[str, Any]] = []
    for host in open_hosts:
        if ended is not None and host.session_id in ended:
            code, _detail = stop_job(host.session_id)
            stopped.append(host.evidence(STOP_JOB_ACTION, code))
    if stopped:
        _report(dispatcher, inventory, hosts=[], reclaimed=stopped, timeout_s=timeout_s)
    reclaimed = [*reclaimed, *stopped]
    for entry in reclaimed:
        _LOGGER.info(
            "reclaimed idle claude host pid=%s session=%s action=%s result=%s "
            "age_seconds=%s rss_kb=%s",
            entry["pid"],
            entry["session_id"],
            entry["action"],
            entry["result"],
            entry["age_seconds"],
            entry["rss_kb"],
        )
    return tuple(reclaimed)


__all__ = [
    "CLAUDE_BACKGROUND_SESSION_KIND",
    "CLAUDE_JOB_ACTIVE_TEMPO",
    "CLAUDE_JOB_EXITED_STATE",
    "HostProcess",
    "IDLE_HOST_THRESHOLD_SECONDS",
    "IdleHost",
    "SIGNAL_HOST_ACTION",
    "STOP_JOB_ACTION",
    "plan_idle_hosts",
    "process_inventory",
    "reclaim_idle_claude_hosts",
    "signal_exited_host",
    "start_epoch",
]
