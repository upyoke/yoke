"""Linux process-tree regressions against the standalone program sent over SSH."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from yoke_harness import linux_command_supervisor as supervisor

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc custody")


@pytest.mark.parametrize("code", [0, 3])
def test_completed_command_keeps_exit_status_and_captures(tmp_path, code):
    directory = tmp_path / "custody"
    source = Path(supervisor.__file__).read_text()
    source += "\nrun_supervised(*[json.loads(a) for a in sys.argv[1:]])"
    command = 'import os,sys; print(os.environ["DISPLAY"]); sys.stderr.write("detail"); sys.exit(int(sys.argv[1]))'
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            source,
            json.dumps(str(directory)),
            json.dumps([sys.executable, "-c", command, str(code)]),
            json.dumps({"DISPLAY": ":10"}),
            json.dumps(2),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0
    settled = supervisor.read_result(str(directory), 0)
    assert settled["receipt"]["returncode"] == code
    assert settled["receipt"]["termination_verified"] is True
    assert settled["stdout"] == ":10\n" and settled["stderr"] == "detail"
    supervisor.remove_settled(str(directory))


@pytest.mark.parametrize("disconnect", [False, True])
def test_nested_term_ignoring_session_cannot_outlive_command(tmp_path, disconnect):
    directory = tmp_path / "custody"
    pidfile = tmp_path / "nested-pid"
    child = "import os,signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path(os.environ['PIDFILE']).write_text(str(os.getpid())); time.sleep(60)"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True); time.sleep(60)"
    source = Path(supervisor.__file__).read_text()
    source += "\nrun_supervised(*[json.loads(a) for a in sys.argv[1:]])"
    guardian = subprocess.Popen(
        [
            sys.executable,
            "-c",
            source,
            json.dumps(str(directory)),
            json.dumps([sys.executable, "-c", parent]),
            json.dumps({"PIDFILE": str(pidfile)}),
            json.dumps(30 if disconnect else 1),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pidfile.exists()
        child_pid = int(pidfile.read_text())
        started = time.monotonic()
        if disconnect:
            guardian.kill()  # SSH guardian vanishes without delivering TERM.
        out, err = guardian.communicate(timeout=5)
        receipt = supervisor.read_receipt(str(directory), 3)
        assert receipt["termination_verified"] is True
        assert receipt["reason"] == ("ssh_disconnected" if disconnect else "deadline")
        assert receipt["returncode"] == 124
        assert time.monotonic() - started < 4
        assert child_pid not in supervisor._alive(
            {child_pid: supervisor._processes().get(child_pid, (0, "", ""))[1]},
            supervisor._processes(),
        )
        if not disconnect:
            assert supervisor.RECEIPT_MARKER in err
        supervisor.remove_settled(str(directory))
        assert not directory.exists()
    finally:
        if guardian.poll() is None:
            guardian.kill()
            guardian.communicate(timeout=2)
        if child_pid is not None and Path(f"/proc/{child_pid}").exists():
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
