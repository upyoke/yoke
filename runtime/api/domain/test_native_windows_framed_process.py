"""Real child-process evidence for framed stdin lifetime and bounded pipe IO."""

import base64
import subprocess
import sys
import time

import pytest

from yoke_harness.native_windows import framed_process
from yoke_harness.native_windows.stdin_frame import frame_bytes


READ_FRAME = """import base64,sys,time
header=sys.stdin.buffer.read(9)
payload=base64.b64decode(sys.stdin.buffer.read(int(header[:8],16)))
"""


def test_frame_finishes_without_eof_and_drains_both_pipes():
    payload = "private synthetic input 雪\n".encode()
    script = READ_FRAME + """
sys.stdout.write(base64.b64encode(payload).decode()+'\\n'+'o'*100000)
sys.stderr.write('e'*100000)
"""
    argv = [sys.executable, "-c", script]
    result = framed_process.run_framed(argv, input=frame_bytes(payload), timeout=10)
    assert result.returncode == 0
    assert result.stdout == base64.b64encode(payload).decode() + "\n" + "o" * 100000
    assert result.stderr == "e" * 100000
    assert payload.decode() not in " ".join(argv)


@pytest.mark.parametrize("blocked_writer", [False, True])
def test_timeout_terminates_child_and_retains_captured_output(monkeypatch, blocked_writer):
    children = []
    real_popen = subprocess.Popen

    def record(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(framed_process.subprocess, "Popen", record)
    script = "import sys,time\n" if blocked_writer else READ_FRAME
    script += "print('before-timeout',flush=True); print('private diagnostic',file=sys.stderr,flush=True); time.sleep(60)"
    payload = b"x" * (1024 * 1024) if blocked_writer else b"synthetic private frame"
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as error:
        framed_process.run_framed([sys.executable, "-c", script], input=frame_bytes(payload), timeout=2)
    assert time.monotonic() - started < 8
    assert "before-timeout" in error.value.stdout
    assert "private diagnostic" in error.value.stderr
    assert len(children) == 1
    assert children[0].poll() is not None
    assert error.value.local_process_pid == children[0].pid
    assert error.value.local_cleanup_verified is True
    assert all(getattr(children[0], name).closed for name in ("stdin", "stdout", "stderr"))


def test_stdin_stays_open_after_complete_frame():
    script = READ_FRAME + "print('frame-consumed',flush=True); sys.stdin.buffer.read(1); print('EOF-observed',flush=True)"
    with pytest.raises(subprocess.TimeoutExpired) as error:
        framed_process.run_framed([sys.executable, "-c", script], input=frame_bytes(b"frame"), timeout=2)
    assert "frame-consumed" in error.value.stdout
    assert "EOF-observed" not in error.value.stdout


def test_remote_refusal_preserves_exit_code_and_diagnostics():
    script = "import sys; print('remote refused',file=sys.stderr,flush=True); sys.exit(9)"
    result = framed_process.run_framed(
        [sys.executable, "-c", script], input=frame_bytes(b"x" * (1024 * 1024)), timeout=10,
    )
    assert result.returncode == 9
    assert result.stderr.strip() == "remote refused"


def test_zero_exit_without_consuming_frame_refuses_incomplete_delivery():
    script = "import sys; print('early success',flush=True); sys.exit(0)"
    with pytest.raises(RuntimeError, match="windows_framed_input_incomplete") as error:
        framed_process.run_framed(
            [sys.executable, "-c", script], input=frame_bytes(b"x" * (1024 * 1024)), timeout=10,
        )
    assert error.value.primary_result.returncode == 0
    assert error.value.primary_result.stdout.strip() == "early success"
    assert isinstance(error.value.__cause__, OSError)


def test_non_ascii_input_refuses_before_process_start(monkeypatch):
    monkeypatch.setattr(framed_process.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("must not start"))
    with pytest.raises(ValueError, match="windows_framed_input_invalid"):
        framed_process.run_framed(["ssh"], input="雪", timeout=1)
