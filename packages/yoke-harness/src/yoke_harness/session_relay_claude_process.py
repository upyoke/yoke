"""Bounded in-memory capture for Claude relay subprocesses."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable, Mapping, Sequence


CLAUDE_STREAM_OUTPUT_LIMIT_BYTES = 64 * 1024
_READ_CHUNK_BYTES = 8 * 1024
_DRAIN_JOIN_SECONDS = 1


@dataclass(frozen=True)
class ClaudeProcessResult:
    returncode: int
    duration_ms: int
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)
    stdout_bytes: bytes = field(default=b"", repr=False)
    stderr_bytes: bytes = field(default=b"", repr=False)
    pid: int | None = None
    bound_exceeded: bool = False

    def with_outcome(self, returncode: int, duration_ms: int) -> "ClaudeProcessResult":
        """Restate this run's outcome while keeping what the native said.

        A create whose identity is resolved by a second step reports that
        step's outcome, and rebuilding the result from scratch is how the
        streams behind it were lost — leaving a native that came up and
        vanished with no reason on record.
        """
        return replace(self, returncode=returncode, duration_ms=duration_ms)


def _drain(stream, retained: dict[str, bytes], name: str) -> None:
    bounded = bytearray()
    try:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            available = CLAUDE_STREAM_OUTPUT_LIMIT_BYTES - len(bounded)
            if available > 0:
                bounded.extend(chunk[:available])
    except (OSError, ValueError):
        pass
    retained[name] = bytes(bounded)


def _finish_drains(threads, streams) -> None:
    for thread in threads:
        thread.join(_DRAIN_JOIN_SECONDS)
    for thread, stream in zip(threads, streams, strict=True):
        if thread.is_alive():
            stream.close()
    for thread in threads:
        thread.join(_DRAIN_JOIN_SECONDS)
        if thread.is_alive():
            raise RuntimeError("native output drain did not stop")


def run_bounded_claude_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    continue_while_alive: bool = False,
    hard_timeout_seconds: float | None = None,
    on_started: Callable[[int], None] | None = None,
    on_bound_exceeded: Callable[[int, int], None] | None = None,
    on_hard_timeout: Callable[[int], None] | None = None,
    start_new_session: bool = False,
) -> ClaudeProcessResult:
    """Drain both streams while a live slow create continues to its hard deadline."""
    started = time.monotonic()
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=start_new_session,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise RuntimeError("native process streams were not captured")
    streams = (process.stdout, process.stderr)
    retained: dict[str, bytes] = {}
    threads = tuple(
        threading.Thread(
            target=_drain,
            args=(stream, retained, name),
            daemon=True,
        )
        for stream, name in zip(streams, ("stdout", "stderr"), strict=True)
    )
    for thread in threads:
        thread.start()
    raw_pid = getattr(process, "pid", None)
    pid = int(raw_pid) if isinstance(raw_pid, int) and raw_pid > 0 else None
    try:
        if on_started is not None:
            if pid is None:
                raise RuntimeError("native process did not expose a pid")
            on_started(pid)
    except Exception:
        process.kill()
        process.wait()
        _finish_drains(threads, streams)
        raise
    timed_out = False
    bound_exceeded = False
    try:
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            if not continue_while_alive:
                process.kill()
                returncode = process.wait()
                timed_out = True
            else:
                polled = process.poll()
                if polled is not None:
                    returncode = int(polled)
                else:
                    bound_exceeded = True
                    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
                    if on_bound_exceeded is not None and pid is not None:
                        on_bound_exceeded(pid, elapsed_ms)
                    remaining = None
                    if hard_timeout_seconds is not None:
                        elapsed = max(0.0, time.monotonic() - started)
                        remaining = max(0.0, hard_timeout_seconds - elapsed)
                    try:
                        returncode = process.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        if on_hard_timeout is not None and pid is not None:
                            on_hard_timeout(pid)
                        if process.poll() is None:
                            process.kill()
                        returncode = process.wait()
                        timed_out = True
    finally:
        _finish_drains(threads, streams)
    if timed_out:
        raise subprocess.TimeoutExpired(
            list(argv), hard_timeout_seconds or timeout_seconds
        )
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    stdout_bytes = retained.get("stdout", b"")
    stderr_bytes = retained.get("stderr", b"")
    return ClaudeProcessResult(
        returncode,
        duration_ms,
        stdout_bytes.decode("utf-8", errors="ignore"),
        stderr_bytes.decode("utf-8", errors="ignore"),
        stdout_bytes,
        stderr_bytes,
        pid,
        bound_exceeded,
    )
