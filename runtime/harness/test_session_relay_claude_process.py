"""Bounded Claude native output collection tests."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import threading

from yoke_core.domain.session_launch_types import LAUNCH_LEASE_SECONDS
from yoke_harness import session_relay_claude_process as process_module
from yoke_harness.session_relay import (
    RELAY_DISPATCH_TIMEOUT_SECONDS,
    RELAY_REPORT_TIMEOUT_SECONDS,
)
from yoke_harness.session_relay_claude import CLAUDE_NATIVE_TIMEOUT_SECONDS
from yoke_harness.session_relay_claude_identity import (
    CLAUDE_IDENTITY_LOOKUP_ATTEMPTS,
    CLAUDE_IDENTITY_RETRY_SECONDS,
)
from yoke_harness.session_relay_claude_process import (
    CLAUDE_STREAM_OUTPUT_LIMIT_BYTES,
    run_bounded_claude_process,
)


class _OversizedStream:
    def __init__(self, payload: bytes) -> None:
        self._buffer = BytesIO(payload)
        self.drained = threading.Event()
        self.read_sizes: list[int] = []
        self.total_read = 0

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        chunk = self._buffer.read(size)
        self.total_read += len(chunk)
        if not chunk:
            self.drained.set()
        return chunk

    def close(self) -> None:
        self._buffer.close()


class _Process:
    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        self.stdout = _OversizedStream(stdout)
        self.stderr = _OversizedStream(stderr)
        self.killed = False

    def wait(self, timeout=None) -> int:
        assert timeout == 3
        assert self.stdout.drained.wait(1)
        assert self.stderr.drained.wait(1)
        return 0

    def kill(self) -> None:
        self.killed = True


def test_process_drains_oversized_streams_while_retaining_only_the_cap(
    monkeypatch,
) -> None:
    limit = CLAUDE_STREAM_OUTPUT_LIMIT_BYTES
    stdout = b"x" * (limit * 3) + b"private-stdout-tail"
    stderr = b"y" * (limit * 2) + b"private-stderr-tail"
    process = _Process(stdout, stderr)
    popen_calls = []

    def fake_popen(argv, **kwargs):
        popen_calls.append((argv, kwargs))
        return process

    monotonic = iter((10.0, 10.012))
    monkeypatch.setattr(process_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(process_module.time, "monotonic", lambda: next(monotonic))

    result = run_bounded_claude_process(
        ("/opt/claude", "--bg", "opaque instruction"),
        cwd=Path("/project"),
        environment={"SAFE": "1"},
        timeout_seconds=3,
    )

    assert process.stdout.total_read == len(stdout)
    assert process.stderr.total_read == len(stderr)
    assert max(process.stdout.read_sizes + process.stderr.read_sizes) <= 8 * 1024
    assert len(result.stdout.encode()) == limit
    assert len(result.stderr.encode()) == limit
    assert "private-stdout-tail" not in result.stdout
    assert "private-stderr-tail" not in result.stderr
    assert result.duration_ms == 12
    assert popen_calls[0][1]["stdout"] is process_module.subprocess.PIPE
    assert popen_calls[0][1]["stderr"] is process_module.subprocess.PIPE
    assert popen_calls[0][1]["env"] == {"SAFE": "1"}


def test_claude_create_and_report_budget_fits_launch_lease() -> None:
    process_count = 1 + CLAUDE_IDENTITY_LOOKUP_ATTEMPTS
    # stdout/stderr are joined once before and once after close.
    drain_budget = process_count * 2 * 2 * process_module._DRAIN_JOIN_SECONDS
    native_budget = process_count * CLAUDE_NATIVE_TIMEOUT_SECONDS
    retry_budget = (CLAUDE_IDENTITY_LOOKUP_ATTEMPTS - 1) * CLAUDE_IDENTITY_RETRY_SECONDS

    assert (
        native_budget
        + drain_budget
        + retry_budget
        + RELAY_DISPATCH_TIMEOUT_SECONDS
        + RELAY_REPORT_TIMEOUT_SECONDS
        < LAUNCH_LEASE_SECONDS
    )
