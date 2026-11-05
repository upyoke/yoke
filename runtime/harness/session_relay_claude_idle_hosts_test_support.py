# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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

from yoke_contracts.timestamps import parse_instant

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

PROCESS_NOW = 1_800_000_000.0

NOW = datetime.fromtimestamp(PROCESS_NOW, timezone.utc)

OLD = PROCESS_NOW - 7 * 24 * 3600

STALE = NOW - timedelta(seconds=IDLE_HOST_THRESHOLD_SECONDS + 60)

FRESH = NOW - timedelta(seconds=30)

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
    return {"state": state, "tempo": tempo, "updated_at": updated}


def _fixture():
    """A process table with one spare per rule, keyed by what should happen."""
    processes = {
        101: _process(101),  # exited job, idle: signalled
        102: _process(102),  # busy: has a child
        103: _process(103, ppid=102, name="zsh"),
        104: _process(104, start=PROCESS_NOW - 5),  # newest spare: the warm pool
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
        104: _record("a0000104-0000-4000-8000-000000000104", started=PROCESS_NOW - 2),
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
