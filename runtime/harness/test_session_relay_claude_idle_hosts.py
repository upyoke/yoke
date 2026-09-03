"""Reclaiming the Claude hosts that ended sessions leave idle on a machine."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

from yoke_contracts.process_ancestry import (
    CLAUDE_BACKGROUND_SPARE_PROCESS_NAME,
    process_start_time,
)
from yoke_contracts.session_control.function_ids import RELAY_IDLE_HOSTS_FUNCTION_ID
from yoke_harness import session_relay_claude_idle_hosts as idle_hosts
from yoke_harness.claude_runtime_records import (
    claude_job_state,
    claude_session_record,
)
from yoke_harness.session_relay_claude_idle_hosts import (
    IDLE_HOST_THRESHOLD_SECONDS,
    SIGNAL_HOST_ACTION,
    STOP_JOB_ACTION,
    HostProcess,
    IdleHost,
    plan_idle_hosts,
    process_inventory,
    reclaim_idle_claude_hosts,
    signal_exited_host,
    start_epoch,
)


NOW = 1_800_000_000.0
OLD = NOW - 7 * 24 * 3600
STALE = NOW - IDLE_HOST_THRESHOLD_SECONDS - 60
FRESH = NOW - 30
SPARE = CLAUDE_BACKGROUND_SPARE_PROCESS_NAME


class _Inventory:
    relay_id = "machine:test"
    machine_id = "machine-1"
    project_ids = (1,)


class _Response:
    def __init__(self, success: bool, result=None, error=None) -> None:
        self.success = success
        self.result = result
        self.error = error


class _Dispatcher:
    def __init__(self, *responses: _Response) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses)

    def __call__(self, *, function_id, target, payload, timeout_s):
        del target, timeout_s
        self.calls.append({"function_id": function_id, **payload})
        return self._responses.pop(0)


def _process(pid: int, name: str = SPARE, *, ppid: int = 1, start=OLD, rss=500_000):
    return HostProcess(pid, ppid, name, start, rss)


def _record(session_id: str, *, started=OLD + 60, kind="bg"):
    return {
        "session_id": session_id,
        "kind": kind,
        "job_id": session_id[:8],
        "started_epoch": started,
    }


def _job(state: str, *, updated=STALE, tempo="idle"):
    return {"state": state, "tempo": tempo, "updated_epoch": updated}


def _fixture():
    """A process table with one spare per rule, keyed by what should happen."""
    processes = {
        101: _process(101),  # exited job, idle: signalled
        102: _process(102),  # busy: has a child
        103: _process(103, ppid=102, name="zsh"),
        104: _process(104, start=NOW - 5),  # newest spare: the warm pool
        105: _process(105),  # job moved recently
        106: _process(106),  # no session record: never claimed
        107: _process(107),  # mid-turn
        108: _process(108, start=OLD + 3600),  # record older than process: reused pid
        109: _process(109),  # open job, idle: asked about
        110: _process(110),  # interactive session, not a background job
        111: _process(111),  # job record missing entirely
    }
    records = {
        101: _record("a0000101-0000-4000-8000-000000000101"),
        102: _record("a0000102-0000-4000-8000-000000000102"),
        104: _record("a0000104-0000-4000-8000-000000000104", started=NOW - 2),
        105: _record("a0000105-0000-4000-8000-000000000105"),
        107: _record("a0000107-0000-4000-8000-000000000107"),
        108: _record("a0000108-0000-4000-8000-000000000108", started=OLD + 60),
        109: _record("a0000109-0000-4000-8000-000000000109"),
        110: _record("a0000110-0000-4000-8000-000000000110", kind="interactive"),
        111: _record("a0000111-0000-4000-8000-000000000111"),
    }
    jobs = {
        records[101]["job_id"]: _job("stopped"),
        records[102]["job_id"]: _job("done"),
        records[104]["job_id"]: _job("done"),
        records[105]["job_id"]: _job("done", updated=FRESH),
        records[107]["job_id"]: _job("working", updated=STALE, tempo="active"),
        records[108]["job_id"]: _job("done"),
        records[109]["job_id"]: _job("done"),
        records[110]["job_id"]: _job("done"),
    }
    return processes, records.get, jobs.get


def test_plan_names_only_idle_used_hosts_and_keeps_the_newest_spare() -> None:
    processes, record_of, job_of = _fixture()
    hosts = plan_idle_hosts(
        processes, now=NOW, session_record_of=record_of, job_state_of=job_of
    )
    assert [(host.pid, host.exited) for host in hosts] == [(101, True), (109, False)]
    signalled = hosts[0]
    assert signalled.age_seconds == int(NOW - OLD)
    assert signalled.idle_seconds == IDLE_HOST_THRESHOLD_SECONDS + 60
    assert signalled.rss_kb == 500_000
    assert signalled.job_state == "stopped"


def test_exited_hosts_are_signalled_and_ended_open_hosts_stopped_via_claude() -> None:
    processes, record_of, job_of = _fixture()
    open_session = record_of(109)["session_id"]
    dispatcher = _Dispatcher(
        _Response(True, {"ended": [open_session], "skipped": []}),
        _Response(True, {"ended": [], "skipped": [], "recorded": [open_session]}),
    )
    signalled: list[int] = []
    stopped: list[str] = []

    def signal_host(host: IdleHost) -> str:
        signalled.append(host.pid)
        return "terminated"

    def stop_job(job_id: str):
        stopped.append(job_id)
        return "terminated", {"background_agent_stop": "completed"}

    reclaimed = reclaim_idle_claude_hosts(
        dispatcher,
        _Inventory(),
        processes=processes,
        now=NOW,
        session_record_of=record_of,
        job_state_of=job_of,
        signal_host=signal_host,
        stop_job=stop_job,
    )
    assert signalled == [101]
    # The job is stopped by the id Claude's own session record names, never by
    # the session UUID: the listing that would resolve one from the other is
    # drained under a byte bound this machine's agent list already overruns.
    assert stopped == [record_of(109)["job_id"]]
    assert open_session not in stopped
    assert [
        (entry["pid"], entry["action"], entry["result"]) for entry in reclaimed
    ] == [
        (101, SIGNAL_HOST_ACTION, "terminated"),
        (109, STOP_JOB_ACTION, "terminated"),
    ]
    first, second = dispatcher.calls
    assert first["function_id"] == RELAY_IDLE_HOSTS_FUNCTION_ID
    assert first["machine_id"] == "machine-1" and first["projects"] == [1]
    assert first["hosts"] == [{"session_id": open_session, "pid": 109}]
    assert first["reclaimed"] == [reclaimed[0]]
    assert second["hosts"] == [] and second["reclaimed"] == [reclaimed[1]]


def test_a_tracked_host_whose_session_is_live_is_never_touched() -> None:
    processes, record_of, job_of = _fixture()
    dispatcher = _Dispatcher(_Response(True, {"ended": [], "skipped": []}))
    stopped: list[str] = []
    reclaimed = reclaim_idle_claude_hosts(
        dispatcher,
        _Inventory(),
        processes=processes,
        now=NOW,
        session_record_of=record_of,
        job_state_of=job_of,
        signal_host=lambda host: "terminated",
        stop_job=lambda job_id: (stopped.append(job_id), ("failed", {}))[1],
    )
    assert stopped == []
    assert [entry["pid"] for entry in reclaimed] == [101]
    assert len(dispatcher.calls) == 1


def test_a_refusing_control_plane_stops_nothing_it_was_asked_about() -> None:
    processes, record_of, job_of = _fixture()
    dispatcher = _Dispatcher(_Response(False, error=type("E", (), {"code": "skew"})()))
    stopped: list[str] = []
    reclaim_idle_claude_hosts(
        dispatcher,
        _Inventory(),
        processes=processes,
        now=NOW,
        session_record_of=record_of,
        job_state_of=job_of,
        signal_host=lambda host: "terminated",
        stop_job=lambda job_id: (stopped.append(job_id), ("failed", {}))[1],
    )
    assert stopped == []
    assert len(dispatcher.calls) == 1


def test_no_spares_means_no_dispatch() -> None:
    dispatcher = _Dispatcher()
    assert (
        reclaim_idle_claude_hosts(
            dispatcher, _Inventory(), processes={1: _process(1, "launchd")}, now=NOW
        )
        == ()
    )
    assert dispatcher.calls == []


def test_signal_exited_host_terminates_the_recorded_process(monkeypatch) -> None:
    monkeypatch.setattr(idle_hosts, "TERMINATE_WAIT_SECONDS", 2.0)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        started = start_epoch(process_start_time(process.pid))
        assert started is not None
        host = IdleHost(process.pid, "s", "j", "stopped", started, 1, 1, 1, True)
        assert signal_exited_host(host) in {"terminated", "killed"}
        assert process.wait(timeout=5) is not None
        assert signal_exited_host(host) == "already_exited"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_process_inventory_reads_titles_and_starts_from_one_ps_call(monkeypatch):
    stamp = "Thu Sep  3 15:51:11 2026"
    rows = [
        f"12817 12749 464384 {stamp} {SPARE}",
        f"12749 24033 113488 {stamp} claude bg-pty-host",
        "bad line",
    ]
    monkeypatch.setattr(idle_hosts, "ps_lines", lambda args: rows)
    table = process_inventory()
    assert set(table) == {12817, 12749}
    spare = table[12817]
    assert (spare.ppid, spare.name, spare.rss_kb) == (12749, SPARE, 464384)
    assert spare.start_epoch == time.mktime(
        time.strptime(stamp, "%a %b %d %H:%M:%S %Y")
    )


def test_claude_records_are_read_bounded_and_normalised(tmp_path: Path) -> None:
    session_id = "17404cc3-93a5-4822-9dcc-778142eccac1"
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "12817.json").write_text(
        json.dumps(
            {
                "pid": 12817,
                "sessionId": session_id,
                "kind": "bg",
                "jobId": session_id[:8],
                "startedAt": 1788465140302,
            }
        )
    )
    job = tmp_path / "jobs" / session_id[:8]
    job.mkdir(parents=True)
    (job / "state.json").write_text(
        json.dumps(
            {
                "state": "done",
                "tempo": "idle",
                "sessionId": session_id,
                "updatedAt": "2026-09-03T20:08:00.176Z",
            }
        )
    )
    assert claude_session_record(12817, tmp_path) == {
        "session_id": session_id,
        "kind": "bg",
        "job_id": session_id[:8],
        "started_epoch": 1788465140.302,
    }
    assert claude_session_record(999, tmp_path) is None
    state = claude_job_state(session_id[:8], tmp_path)
    assert state["state"] == "done" and state["tempo"] == "idle"
    assert int(state["updated_epoch"]) == 1788466080
    assert claude_job_state("../jobs", tmp_path) is None
    assert claude_job_state("missing0", tmp_path) is None
