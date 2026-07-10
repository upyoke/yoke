"""Chunk-safe stream redaction for runner-fleet child processes."""

from __future__ import annotations

from io import StringIO
import subprocess

import pytest

from yoke_core.tools.runner_fleet_redacted_process import (
    run_redacted_child,
)
from runtime.api.tools.runner_fleet_exec_test_support import (
    _ChunkedStream,
    _Process,
    _TOKEN,
)


@pytest.mark.parametrize("split_at", range(1, len(_TOKEN)))
def test_token_is_redacted_at_every_read_boundary_on_both_streams(
    split_at,
):
    process = _Process(
        returncode=23,
        stdout=(
            b"stdout-before:",
            _TOKEN[:split_at].encode("utf-8"),
            _TOKEN[split_at:].encode("utf-8"),
            b":stdout-after",
            b"!",
        ),
        stderr=(
            b"stderr-before:",
            _TOKEN[:split_at].encode("utf-8"),
            _TOKEN[split_at:].encode("utf-8"),
            b":stderr-after",
            b"?",
        ),
    )
    calls = []

    def child_factory(argv, **kwargs):
        calls.append((argv, kwargs))
        return process

    out = StringIO()
    err = StringIO()
    result = run_redacted_child(
        ["pulumi", "up", "--yes"],
        env={"GITHUB_TOKEN": _TOKEN},
        redaction_terms=[_TOKEN],
        child_factory=child_factory,
        out=out,
        err=err,
    )

    assert result.returncode == 23
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == ["pulumi", "up", "--yes"]
    assert _TOKEN not in argv
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["bufsize"] == 0
    assert kwargs["start_new_session"] is True
    assert out.getvalue() == "stdout-before:[REDACTED]:stdout-after!"
    assert err.getvalue() == "stderr-before:[REDACTED]:stderr-after?"
    assert _TOKEN not in out.getvalue()
    assert _TOKEN not in err.getvalue()
    assert process.stdout.closed is True
    assert process.stderr.closed is True


def test_keyboard_interrupt_stops_child_and_reraises():
    class InterruptingProcess:
        def __init__(self):
            self.stdout = _ChunkedStream(())
            self.stderr = _ChunkedStream(())
            self.terminated = False
            self.killed = False
            self.wait_calls = 0

        def wait(self, timeout=None):
            del timeout
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise KeyboardInterrupt
            return -15

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    process = InterruptingProcess()
    with pytest.raises(KeyboardInterrupt):
        run_redacted_child(
            ["pulumi", "up", "--yes"],
            env={},
            redaction_terms=[_TOKEN],
            child_factory=lambda *args, **kwargs: process,
            out=StringIO(),
            err=StringIO(),
        )

    assert process.terminated is True
    assert process.killed is False
    assert process.wait_calls == 2
    assert process.stdout.closed is True
    assert process.stderr.closed is True
