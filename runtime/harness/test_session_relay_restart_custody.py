"""A fresh relay settles durable custody after its predecessor stops abruptly."""

from functools import partial
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

from yoke_harness.session_launch_containment import supervision_record_path
from yoke_harness.session_relay_daemon import serve_forever
from yoke_harness.session_relay_resume_settlement import settle_finished_native_resumes
from yoke_contracts.session_control.resume import RESUMED_DIED_RESULT


def test_next_start_reconciles_custody_before_accepting_more_work(tmp_path: Path):
    attempt, session, lease = str(uuid4()), str(uuid4()), str(uuid4())
    ready = tmp_path / "ready"
    program = """
import os, sys, time
from pathlib import Path
from yoke_harness.session_launch_containment import record_supervised_native
from yoke_harness.session_relay_native_capture_format import compose_capture, STATE_RUNNING
root, attempt, session, lease = Path(sys.argv[1]), *sys.argv[2:]
capture = root / 'interrupted.capture'
capture.write_bytes(compose_capture(stdout=b'', stderr=b'', state=STATE_RUNNING))
assert record_supervised_native(attempt, os.getpid(), native_session_id=session,
    supervision_kind='resume', capture_path=capture, lease_id=lease, state_dir=root)
(root / 'ready').touch()
time.sleep(60)
"""
    previous = subprocess.Popen(
        [sys.executable, "-c", program, str(tmp_path), attempt, session, lease],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and previous.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), previous.communicate(timeout=1)
        previous.kill()  # No signal-drain grace: Windows service-stop counterpart.
        previous.communicate(timeout=5)
    finally:
        if previous.poll() is None:
            previous.kill()
            previous.communicate(timeout=5)

    record = supervision_record_path(attempt, tmp_path)
    assert record.exists()
    reports = []

    def dispatch(**kwargs):
        reports.append(kwargs["payload"])
        return SimpleNamespace(success=True)

    def poll(**_kwargs):
        assert not record.exists()
        assert len(reports) == 1
        return SimpleNamespace(state="active")

    settle = partial(
        settle_finished_native_resumes, dispatch, "resume.report",
        relay_id="machine:relay", machine_id=str(uuid4()),
        state_dir=tmp_path, custody_state_dir=tmp_path, timeout_s=5,
    )
    serve_forever(
        state_dir=tmp_path, cycle=poll, cycle_maintenance=settle,
        stop_after_cycles=1, install_signals=False,
    )
    assert reports[0]["job_id"] == attempt
    assert reports[0]["lease_id"] == lease
    assert reports[0]["result"] == RESUMED_DIED_RESULT
    assert "exit_code" not in reports[0]["evidence"]
    assert settle() == ()
    assert len(reports) == 1
