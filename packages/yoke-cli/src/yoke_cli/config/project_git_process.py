"""Hard wall-clock and output boundaries for network-capable Git children."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


NETWORK_GIT_TIMEOUT_SECONDS = 600.0
NETWORK_GIT_OUTPUT_MAX_BYTES = 4 * 1024 * 1024
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
    pass_fds: Sequence[int] = (),
    cwd_fd: int | None = None,
) -> NetworkGitResult:
    """Run one network Git command with bounded pipes and group termination."""

    if timeout_seconds <= 0 or maximum_output_bytes <= 0:
        raise ValueError("network Git boundaries must be positive")
    selected = tuple(str(part) for part in command)
    launched = selected
    inherited = tuple(pass_fds)
    if cwd_fd is not None:
        if cwd is not None or cwd_fd < 0:
            raise ValueError("descriptor cwd cannot be combined with a path cwd")
        launched = (
            sys.executable,
            "-m",
            "yoke_cli.config.project_git_fd_exec",
            str(cwd_fd),
            "--",
            *selected,
        )
        inherited = tuple(dict.fromkeys((*inherited, cwd_fd)))
    try:
        process = subprocess.Popen(
            launched,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            pass_fds=inherited,
        )
    except OSError as exc:
        raise NetworkGitBoundaryError("network Git could not be started") from exc
    assert process.stdout is not None
    assert process.stderr is not None
    streams = {process.stdout: bytearray(), process.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
    deadline = monotonic() + timeout_seconds
    try:
        while selector.get_map():
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise NetworkGitBoundaryError(
                    "network Git exceeded its operation deadline"
                )
            for key, _events in selector.select(min(remaining, 0.25)):
                stream = key.fileobj
                chunk = os.read(stream.fileno(), _READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(stream)
                    continue
                captured = streams[stream]
                if len(captured) + len(chunk) > maximum_output_bytes:
                    raise NetworkGitBoundaryError(
                        "network Git exceeded its diagnostic output limit"
                    )
                captured.extend(chunk)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise NetworkGitBoundaryError(
                "network Git exceeded its operation deadline"
            )
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise NetworkGitBoundaryError(
                "network Git exceeded its operation deadline"
            ) from exc
    except NetworkGitBoundaryError:
        _terminate_process_group(process)
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    return NetworkGitResult(
        args=selected,
        returncode=returncode,
        stdout=_decode(streams[process.stdout]),
        stderr=_decode(streams[process.stderr]),
    )


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _decode(value: bytearray) -> str:
    return bytes(value).decode("utf-8", errors="replace")


__all__ = [
    "NETWORK_GIT_OUTPUT_MAX_BYTES",
    "NETWORK_GIT_TIMEOUT_SECONDS",
    "NetworkGitBoundaryError",
    "NetworkGitResult",
    "run_network_git",
]
