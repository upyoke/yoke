"""Early-closing stdout consumers do not receive a CLI traceback."""

import os
import subprocess
import sys

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
