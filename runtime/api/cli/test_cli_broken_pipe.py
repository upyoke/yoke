"""Early-closing stdout consumers do not receive a CLI traceback."""

import os
import subprocess
import sys

import pytest

from yoke_cli.cli_output import quiet_closed_stdout


def test_help_can_be_piped_to_a_reader_that_closes_early():
    reader, writer = os.pipe()
    process = subprocess.Popen(
        [sys.executable, "-m", "yoke_cli.main", "--help"],
        stdout=writer,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.close(writer)
    with os.fdopen(reader) as output:
        assert output.readline().startswith("yoke")
    _, error = process.communicate(timeout=20)
    assert process.returncode == 0
    assert "BrokenPipeError" not in error and "Traceback" not in error


def test_buffered_stdout_flush_is_inside_the_closed_pipe_boundary(monkeypatch):
    class ClosedOutput:
        def flush(self):
            raise BrokenPipeError()

        def fileno(self):
            raise OSError("no descriptor")

    monkeypatch.setattr(sys, "stdout", ClosedOutput())
    assert quiet_closed_stdout(lambda: 0)() == 0


@pytest.mark.parametrize(
    "transport",
    [
        "sender, receiver = socket.socketpair(); receiver.close(); sender.send(b'x')",
        "child = subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.PIPE); "
        "child.wait(); child.stdin.write(b'x'); child.stdin.flush()",
    ],
    ids=["socket", "subprocess"],
)
def test_non_stdout_broken_pipes_remain_nonzero_errors(transport):
    code = (
        "import socket, subprocess, sys\n"
        "from yoke_cli.cli_output import quiet_closed_stdout\n"
        "@quiet_closed_stdout\n"
        "def operation():\n"
        f"    {transport}\n"
        "operation()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "BrokenPipeError" in result.stderr


def test_stderr_broken_pipe_is_not_stdout_success(monkeypatch):
    class ClosedErrorOutput:
        def write(self, value):
            raise BrokenPipeError("stderr closed")

    monkeypatch.setattr(sys, "stderr", ClosedErrorOutput())
    with pytest.raises(BrokenPipeError, match="stderr closed"):
        quiet_closed_stdout(lambda: print("failure", file=sys.stderr))()
