"""Remote authorization emits progress before completion without losing receipts."""

from io import StringIO
import subprocess
import sys

import pytest

from yoke_harness.test_machine_remote_exec import _stream_command
from yoke_harness.test_machine_gui_command import _Progress
from yoke_harness import test_machine_gui_command as gui


def test_streamed_progress_arrives_while_child_is_waiting(tmp_path):
    release = tmp_path / "release"
    output, errors = StringIO(), StringIO()

    class Progress(StringIO):
        def write(self, value):
            result = super().write(value)
            if "verifying" in self.getvalue():
                release.touch()
            return result

    output = Progress()
    command = [
        sys.executable,
        "-c",
        (
            "import pathlib,time; print('verifying',flush=True); "
            f"p=pathlib.Path({str(release)!r}); "
            "exec('while not p.exists(): time.sleep(0.01)'); "
            "print('signed in')"
        ),
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result = _stream_command(
        command, process=process, stdout=output, stderr=errors, timeout=3
    )
    assert result.returncode == 0 and release.exists()
    assert "signed in" in output.getvalue()
    assert result.stdout == output.getvalue()


def test_stream_redacts_secret_without_sending_it_to_stdin():
    output, errors = StringIO(), StringIO()
    command = [sys.executable, "-c", "print('private-password verifying')"]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result = _stream_command(
        command,
        process=process,
        redaction_secret="private-password",
        stdout=output,
        stderr=errors,
    )
    assert "private-password" not in output.getvalue() + result.stdout
    assert "[REDACTED]" in output.getvalue()


def test_control_receipts_do_not_hide_operator_progress():
    destination = StringIO()
    stream = _Progress(destination, control_lines=True)
    stream.write("YOKE_COMMAND_HEART")
    stream.write('BEAT\nverifying\nYOKE_COMMAND_RECEIPT:{"ok":true}\n')
    stream.write("final diagnostic")
    stream.finish()
    assert destination.getvalue() == "verifying\nfinal diagnostic"


def test_streamed_child_timeout_is_bounded():
    command = [sys.executable, "-c", "import time; time.sleep(10)"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with pytest.raises(subprocess.TimeoutExpired):
        _stream_command(command, process=process, timeout=0.01)
    assert process.poll() is not None


def test_gui_authorization_stream_keeps_json_stdout_clean(
    monkeypatch, tmp_path, capsys
):
    command = [
        sys.executable,
        "-c",
        "import sys; print('verifying',flush=True); print('YOKE_COMMAND_HEARTBEAT',file=sys.stderr)",
    ]
    monkeypatch.setattr(gui, "remote_exec_argv", lambda **kw: command)
    control = gui._GuiSshControl(
        {"os": "linux", "host": "fixture", "user": "tester"}, tmp_path, None, True, True
    )
    result = control._run("authorize", timeout=1920)
    output = capsys.readouterr()
    assert control.streamed and result.returncode == 0
    assert output.out == "" and "verifying" in output.err
    assert "HEARTBEAT" not in output.err
