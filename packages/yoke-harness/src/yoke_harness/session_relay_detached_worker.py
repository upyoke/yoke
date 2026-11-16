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
from typing import Callable, TypeVar


MAX_HANDOFF_BYTES = 64 * 1024
START_TIMEOUT_SECONDS = 35.0

T = TypeVar("T")
ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _stop(process: subprocess.Popen[bytes]) -> None:
    stop_relay_process(process)


def reap_in_background(process: subprocess.Popen[bytes]) -> None:
    """Wait for a child that outlives this call, so its exit never leaves a zombie."""
    threading.Thread(
        target=process.wait,
        daemon=True,
        name="yoke-native-owner-reap",
    ).start()


def _read_json(process: subprocess.Popen[bytes], timeout: float) -> object | None:
    if process.stdout is None:
        return None
    reader = PipeReader(process.stdout)
    deadline = time.monotonic() + timeout
    buffer = bytearray()
    try:
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
    finally:
        reader.close()
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
    try:
        process.stdin.write(body + b"\n")
        process.stdin.flush()
        process.stdin.close()
        sent = True
        outcome = decode(_read_json(process, timeout))
    except (OSError, subprocess.SubprocessError):
        outcome = None
    finally:
        try:
            process.stdout.close()
        except OSError:
            pass
        if process.poll() is None:
            reap_in_background(process)
        else:
            process.wait()
    if outcome is not None:
        return outcome
    return uncertain_failure if sent else initial_failure


__all__ = [
    "MAX_HANDOFF_BYTES",
    "START_TIMEOUT_SECONDS",
    "reap_in_background",
    "run_detached_json_worker",
]
