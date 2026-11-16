"""The relay's pre-claim liveness pass costs one process read, not one per record.

Every poll checks each custody record on the machine before it claims. A
process-table scan per record and a directory re-read per dead session made that pass
take most of a minute on a machine holding a thousand records, so every wake
there waited for the previous one to finish (YOK-5294).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts import process_start_snapshot
from yoke_harness import session_launch_containment
from yoke_harness.session_launch_containment import (
    supervised_records,
    supervised_records_pass,
    supervision_record_path,
)
from yoke_harness.session_relay_process_liveness import verified_dead_sessions


pytestmark = pytest.mark.windows

START = "1787000000.25"
ABSENT_PID = 2_000_000_000


def _resume(state_dir: Path, index: int, *, session: str, pid: int) -> None:
    path = supervision_record_path(f"resume-{index:04d}", state_dir)
    path.write_text(
        json.dumps(
            {
                "supervision_kind": "resume",
                "launch_id": f"resume-{index:04d}",
                "target_session_id": session,
                "pid": pid,
                "process_start_time": START,
                "recorded_at": 1,
            }
        ),
        encoding="utf-8",
    )


OWN = os.getpid()


def _per_pid(answers: dict[int, str | None], asked: list[int]):
    def probe(pid):
        asked.append(pid)
        if pid not in answers:
            pytest.fail(f"per-pid probe for pid {pid}")
        return answers[pid]

    return probe


def test_reader_answers_every_listed_pid_from_one_platform_snapshot(monkeypatch) -> None:
    calls = []

    def snapshot():
        calls.append(True)
        return [SimpleNamespace(pid=pid, start_time=float(START))
                for pid in (OWN, 101)]

    asked: list[int] = []
    monkeypatch.setattr(process_start_snapshot.platform_process, "process_command_lines", snapshot)
    monkeypatch.setattr(
        process_start_snapshot, "process_start_time", _per_pid({OWN: START}, asked)
    )
    reader = process_start_snapshot.process_start_reader()

    assert [reader(101) for _ in range(50)] == [START] * 50
    # A missing process answers as gone without a per-pid table scan.
    assert reader(ABSENT_PID) is None
    assert len(calls) == 1
    # Snapshot and per-pid probe share the platform epoch contract.
    assert asked == []


def test_reader_asks_live_for_a_pid_the_snapshot_missed(monkeypatch) -> None:
    monkeypatch.setattr(
        process_start_snapshot.platform_process, "process_command_lines",
        lambda: [SimpleNamespace(pid=OWN, start_time=float(START))]
    )
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        asked: list[int] = []
        later = "1787000001.5"
        monkeypatch.setattr(
            process_start_snapshot,
            "process_start_time",
            _per_pid({OWN: START, child.pid: later}, asked),
        )
        reader = process_start_snapshot.process_start_reader()

        # A process started after the snapshot still exists, so it is asked.
        assert reader(child.pid) == later
        # A pid with no process at all is gone without a subprocess.
        assert reader(ABSENT_PID) is None
        assert asked == [child.pid]
    finally:
        child.kill()
        child.wait()


@pytest.mark.parametrize("denied", [False, True])
def test_unreadable_table_falls_back_to_the_per_pid_probe(monkeypatch, denied) -> None:
    def snapshot():
        if denied:
            raise OSError("process access denied")
        return []

    monkeypatch.setattr(process_start_snapshot.platform_process, "process_command_lines", snapshot)
    reader = process_start_snapshot.process_start_reader()
    assert reader is process_start_snapshot.process_start_time


def test_record_pass_reads_the_directory_once(tmp_path, monkeypatch) -> None:
    for index in range(3):
        _resume(tmp_path, index, session="s", pid=ABSENT_PID)
    reads: list[Path] = []
    real = session_launch_containment._read_records

    def counting(directory):
        reads.append(directory)
        return real(directory)

    monkeypatch.setattr(session_launch_containment, "_read_records", counting)
    with supervised_records_pass(tmp_path):
        for _ in range(10):
            assert len(list(supervised_records(tmp_path))) == 3
        # A reader cannot change what the next reader in the pass sees.
        next(supervised_records(tmp_path))[1]["pid"] = 1
        assert next(supervised_records(tmp_path))[1]["pid"] == ABSENT_PID
        other = tmp_path / "other"
        assert list(supervised_records(other)) == []
    assert len(reads) == 2
    # Outside the pass every read is live again.
    supervision_record_path("resume-0000", tmp_path).unlink()
    assert len(list(supervised_records(tmp_path))) == 2


def test_reader_tokens_match_the_per_pid_probe_on_this_platform() -> None:
    """Records hold process_start_time tokens; the reader must produce the same.

    A reader whose tokens drifted from the probe that wrote the records would
    read every live native as gone and report its session dead.
    """
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    reader = process_start_snapshot.process_start_reader()
    for pid in (os.getpid(), os.getppid(), child.pid):
        assert reader(pid) == process_start_snapshot.process_start_time(pid)
    assert reader(os.getpid()) is not None


def test_liveness_pass_over_many_records_reads_platform_snapshot_once(tmp_path, monkeypatch) -> None:
    sessions = [f"00000000-0000-4000-8000-{index:012d}" for index in range(20)]
    for index in range(200):
        _resume(tmp_path, index, session=sessions[index % 20], pid=ABSENT_PID)
    snapshot_calls = []

    def snapshot():
        snapshot_calls.append(True)
        return [SimpleNamespace(pid=OWN, start_time=float(START))]

    monkeypatch.setattr(process_start_snapshot.platform_process, "process_command_lines", snapshot)
    asked: list[int] = []
    monkeypatch.setattr(
        process_start_snapshot, "process_start_time", _per_pid({OWN: START}, asked)
    )
    reads: list[Path] = []
    real = session_launch_containment._read_records

    def counting(directory):
        reads.append(directory)
        return real(directory)

    monkeypatch.setattr(session_launch_containment, "_read_records", counting)

    dead = verified_dead_sessions(state_dir=tmp_path, anchors_dir=tmp_path / "anchors")

    assert sorted(entry.session_id for entry in dead) == sorted(sessions)
    assert len(snapshot_calls) == 1
    assert asked == []
    assert reads == [session_launch_containment._directory(tmp_path)]
