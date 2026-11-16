"""Hard wall-clock and output boundaries for network-capable Git children."""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from yoke_contracts.platform_process import GroupHandle, spawn_group, stop_group


NETWORK_GIT_TIMEOUT_SECONDS = 600.0
NETWORK_GIT_OUTPUT_MAX_BYTES = 4 * 1024 * 1024
_STOP_GRACE_SECONDS = 2.0
_READ_CHUNK_BYTES = 64 * 1024


class NetworkGitBoundaryError(RuntimeError):
    """A Git child crossed its time or captured-output safety boundary."""


@dataclass(frozen=True)
class NetworkGitResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def run_network_git(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = NETWORK_GIT_TIMEOUT_SECONDS,
    maximum_output_bytes: int = NETWORK_GIT_OUTPUT_MAX_BYTES,
    monotonic: Callable[[], float] = time.monotonic,
) -> NetworkGitResult:
    """Run one network Git command with bounded pipes and group termination."""

    if timeout_seconds <= 0 or maximum_output_bytes <= 0:
        raise ValueError("network Git boundaries must be positive")
    selected = tuple(str(part) for part in command)
    try:
        group = spawn_group(
            selected,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise NetworkGitBoundaryError("network Git could not be started") from exc
    process = group.process
    assert process is not None
    assert process.stdout is not None
    assert process.stderr is not None
    streams = {process.stdout: bytearray(), process.stderr: bytearray()}
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
    deadline = monotonic() + timeout_seconds
    selector: selectors.BaseSelector | None = None
    try:
        if os.name == "nt":
            _drain_windows_pipes(
                streams,
                deadline=deadline,
                maximum_output_bytes=maximum_output_bytes,
                monotonic=monotonic,
            )
        else:
            selector = selectors.DefaultSelector()
            for stream in streams:
                selector.register(stream, selectors.EVENT_READ)
            _drain_selected_pipes(
                selector,
                streams,
                deadline=deadline,
                maximum_output_bytes=maximum_output_bytes,
                monotonic=monotonic,
            )
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise NetworkGitBoundaryError("network Git exceeded its operation deadline")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise NetworkGitBoundaryError(
                "network Git exceeded its operation deadline"
            ) from exc
    except NetworkGitBoundaryError:
        _terminate_group(group)
        raise
    finally:
        if selector is not None:
            selector.close()
        process.stdout.close()
        process.stderr.close()
    return NetworkGitResult(
        args=selected,
        returncode=returncode,
        stdout=_decode(streams[process.stdout]),
        stderr=_decode(streams[process.stderr]),
    )


def _drain_windows_pipes(
    streams: dict[object, bytearray],
    *,
    deadline: float,
    maximum_output_bytes: int,
    monotonic: Callable[[], float],
) -> None:
    pending = set(streams)
    while pending:
        remaining = _remaining(deadline, monotonic)
        read_any = False
        for stream in tuple(pending):
            try:
                chunk = os.read(stream.fileno(), _READ_CHUNK_BYTES)
            except BlockingIOError:
                continue
            read_any = True
            if not chunk:
                pending.remove(stream)
                continue
            _capture(streams[stream], chunk, maximum_output_bytes)
        if not read_any:
            time.sleep(min(0.05, remaining))


def _drain_selected_pipes(
    selector: selectors.BaseSelector,
    streams: dict[object, bytearray],
    *,
    deadline: float,
    maximum_output_bytes: int,
    monotonic: Callable[[], float],
) -> None:
    while selector.get_map():
        remaining = _remaining(deadline, monotonic)
        for key, _events in selector.select(min(remaining, 0.25)):
            stream = key.fileobj
            chunk = os.read(stream.fileno(), _READ_CHUNK_BYTES)
            if not chunk:
                selector.unregister(stream)
                continue
            _capture(streams[stream], chunk, maximum_output_bytes)


def _remaining(deadline: float, monotonic: Callable[[], float]) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise NetworkGitBoundaryError("network Git exceeded its operation deadline")
    return remaining


def _capture(captured: bytearray, chunk: bytes, maximum_output_bytes: int) -> None:
    if len(captured) + len(chunk) > maximum_output_bytes:
        raise NetworkGitBoundaryError(
            "network Git exceeded its diagnostic output limit"
        )
    captured.extend(chunk)


def _terminate_group(group: GroupHandle) -> None:
    """Stop Git and every helper it started; a stop failure keeps the cause."""
    try:
        stop_group(group, _STOP_GRACE_SECONDS)
    except (OSError, TimeoutError) as exc:
        raise NetworkGitBoundaryError(
            f"network Git crossed its boundary and could not be stopped ({exc}); "
            "end the listed git processes, then retry"
        ) from exc


def _decode(value: bytearray) -> str:
    return bytes(value).decode("utf-8", errors="replace")


__all__ = [
    "NETWORK_GIT_OUTPUT_MAX_BYTES",
    "NETWORK_GIT_TIMEOUT_SECONDS",
    "NetworkGitBoundaryError",
    "NetworkGitResult",
    "run_network_git",
]
