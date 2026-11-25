"""Bounded JSON handoff to a detached native-session owner process."""

from __future__ import annotations

from yoke_harness.session_relay_pipe_reader import PipeReader

from yoke_harness.session_relay_process_group import spawn_relay_process, stop_relay_process

from yoke_harness.session_launch_admission import spawn_admitted_process

import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import BinaryIO, Callable, TypeVar


MAX_HANDOFF_BYTES = 64 * 1024
START_TIMEOUT_SECONDS = 35.0

T = TypeVar("T")
ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _stop(process: subprocess.Popen[bytes]) -> None:
    stop_relay_process(process)


def _close_stream(stream: BinaryIO | None) -> None:
    if stream is not None:
        try:
            stream.close()
        except OSError:
            pass


def reap_and_close_in_background(
    process: subprocess.Popen[bytes],
    stream: BinaryIO | None,
    *,
    reader: PipeReader | None = None,
) -> None:
    """Reap the owner and close stdout once no read can hold the pipe lock."""

    def reap() -> None:
        process.wait()
        if reader is not None:
            # A descendant may keep stdout open after the owner exits.
            reader.thread.join()
        _close_stream(stream)

    threading.Thread(
        target=reap,
        daemon=True,
        name="yoke-native-owner-reap",
    ).start()


def _read_json(reader: PipeReader, timeout: float) -> object | None:
    deadline = time.monotonic() + timeout
    buffer = bytearray()
    while time.monotonic() < deadline:
        try:
            chunk = reader.read(timeout=max(0, deadline - time.monotonic()))
        except TimeoutError:
            break
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > MAX_HANDOFF_BYTES:
            return None
        if b"\n" in buffer:
            try:
                return json.loads(bytes(buffer.partition(b"\n")[0]))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
    return None


def run_detached_json_worker(
    *,
    module: str,
    checkout: Path,
    environment: dict[str, str],
    payload: dict[str, object],
    decode: Callable[[object], T | None],
    initial_failure: T,
    uncertain_failure: T,
    executable: str = sys.executable,
    process_factory: ProcessFactory = spawn_relay_process,
    timeout: float = START_TIMEOUT_SECONDS,
) -> T:
    """Return one bounded outcome while the detached child retains native pipes."""
    try:
        process = spawn_admitted_process(
            [executable, "-m", module],
            process_factory=process_factory,
            cwd=checkout,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return initial_failure
    if process.stdin is None or process.stdout is None:
        _stop(process)
        return initial_failure
    body = json.dumps(payload, separators=(",", ":")).encode()
    if len(body) > MAX_HANDOFF_BYTES:
        _stop(process)
        return initial_failure
    sent = False
    reader = None
    try:
        process.stdin.write(body + b"\n")
        process.stdin.flush()
        process.stdin.close()
        sent = True
        reader = PipeReader(process.stdout)
        outcome = decode(_read_json(reader, timeout))
    except (OSError, subprocess.SubprocessError):
        outcome = None
    finally:
        if reader is not None:
            reader.close()
        if reader is not None and not reader.eof:
            # Windows waits for a pending read when another thread closes stdout.
            reap_and_close_in_background(process, process.stdout, reader=reader)
        else:
            _close_stream(process.stdout)
            if process.poll() is None:
                reap_and_close_in_background(process, None)
    if outcome is not None:
        return outcome
    return uncertain_failure if sent else initial_failure


__all__ = [
    "MAX_HANDOFF_BYTES",
    "START_TIMEOUT_SECONDS",
    "reap_and_close_in_background",
    "run_detached_json_worker",
]
