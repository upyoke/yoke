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


# Each OS names a closed transport differently: POSIX raises BrokenPipeError
# (EPIPE). Windows reports a pipe whose reader exited as EINVAL (the case
# subprocess.communicate already treats as a broken pipe) and a loopback socket
# whose peer closed as an aborted or reset connection once its RST arrives.
_CLOSED_TRANSPORT_ERRORS = {
    "socket": (
        ("ConnectionAbortedError", "ConnectionResetError")
        if os.name == "nt"
        else ("BrokenPipeError",)
    ),
    "subprocess": (
        ("OSError: [Errno 22] Invalid argument",)
        if os.name == "nt"
        else ("BrokenPipeError",)
    ),
}


@pytest.mark.parametrize(
    "transport",
    [
        "sender, receiver = socket.socketpair(); receiver.close()\n"
        "    while True: sender.send(b'x')",
        "child = subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.PIPE); "
        "child.wait(); child.stdin.write(b'x'); child.stdin.flush()",
    ],
    ids=["socket", "subprocess"],
)
def test_non_stdout_broken_pipes_remain_nonzero_errors(request, transport):
    code = (
        "import socket, subprocess, sys\n"
        "from yoke_cli.cli_output import quiet_closed_stdout\n"
        "@quiet_closed_stdout\n"
        "def operation():\n"
        f"    {transport}\n"
        "operation()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
    )
    assert result.returncode != 0
    closed = _CLOSED_TRANSPORT_ERRORS[request.node.callspec.id]
    assert any(error in result.stderr for error in closed), result.stderr


def test_stderr_broken_pipe_is_not_stdout_success(monkeypatch):
    class ClosedErrorOutput:
        def write(self, value):
            raise BrokenPipeError("stderr closed")

    monkeypatch.setattr(sys, "stderr", ClosedErrorOutput())
    with pytest.raises(BrokenPipeError, match="stderr closed"):
        quiet_closed_stdout(lambda: print("failure", file=sys.stderr))()


@pytest.mark.parametrize("os_name, quiet", [("nt", True), ("posix", False)])
def test_windows_einval_on_stdout_is_a_closed_reader(monkeypatch, os_name, quiet):
    import errno

    from yoke_cli import cli_output

    class ClosedOutput:
        def write(self, value):
            raise OSError(errno.EINVAL, "Invalid argument")

        def flush(self):
            pass

        def fileno(self):
            raise OSError("no descriptor")

    monkeypatch.setattr(cli_output.os, "name", os_name)
    monkeypatch.setattr(sys, "stdout", ClosedOutput())
    run = quiet_closed_stdout(lambda: print("output"))
    if quiet:
        assert run() == 0
    else:
        with pytest.raises(OSError, match="Invalid argument"):
            run()
