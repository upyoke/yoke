"""Bounded in-memory capture for Claude relay subprocesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import threading
import time
from typing import Mapping, Sequence


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
    timeout_seconds: int,
) -> ClaudeProcessResult:
    """Drain both streams continuously while retaining only their capped prefix."""
    started = time.monotonic()
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
    timed_out = False
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        returncode = process.wait()
    finally:
        _finish_drains(threads, streams)
    if timed_out:
        raise subprocess.TimeoutExpired(list(argv), timeout_seconds)
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
    )
