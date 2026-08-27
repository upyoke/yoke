"""Detached Claude resume spawn with private capture and local custody."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence
from uuid import UUID

from yoke_contracts.session_control.resume import RESUMED_RUNNING_RESULT
from yoke_harness.session_launch_containment import record_supervised_native
from yoke_harness.session_relay_native_diagnostics import (
    NATIVE_DIAGNOSTIC_TTL_SECONDS,
)
from yoke_harness import session_relay_resume_watch
from yoke_harness.session_relay_resume_watch import (
    OUTCOME_SUFFIX,
    resume_outcome_path,
)
from yoke_harness.session_relay_schedule import relay_state_dir


CAPTURE_DIRECTORY_NAME = "claude-resume-captures"
CAPTURE_RETENTION_SECONDS = NATIVE_DIAGNOSTIC_TTL_SECONDS
ProcessFactory = Callable[..., subprocess.Popen[bytes]]


@dataclass(frozen=True)
class ClaudeResumeProcess:
    """Safe spawn facts returned before the resumed turn completes.

    ``pid`` names the leader of the resume's process group — the supervisor
    that waits for the native and records how it ended. Containing the resume
    means signalling that group, so one pid still covers the whole resume.
    """

    pid: int
    binary: str
    binary_source: str
    capture_path: Path
    started_at: str
    background_job: Mapping[str, str] = field(default_factory=dict)

    @property
    def evidence(self) -> dict[str, str | int]:
        return {
            "result_code": RESUMED_RUNNING_RESULT,
            "native_pid": self.pid,
            "native_binary": self.binary,
            "native_binary_source": self.binary_source,
            "native_capture_path": str(self.capture_path),
            "native_started_at": self.started_at,
            **self.background_job,
        }


def _capture_directory(state_dir: Path | None) -> Path:
    directory = (state_dir or relay_state_dir()) / CAPTURE_DIRECTORY_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory


def _cleanup_captures(directory: Path, *, now: float) -> None:
    try:
        captures = tuple(directory.glob("*.capture")) + tuple(
            directory.glob(f"*{OUTCOME_SUFFIX}")
        )
    except OSError:
        return
    for path in captures:
        try:
            if now - path.stat().st_mtime >= CAPTURE_RETENTION_SECONDS:
                path.unlink()
        except OSError:
            continue


def _capture_file(directory: Path, attempt_id: str) -> tuple[Path, object]:
    UUID(attempt_id)
    path = directory / f"{attempt_id}.capture"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    return path, os.fdopen(descriptor, "wb", closefd=True)


def _stop_uncontained(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        try:
            process.terminate()
        except OSError:
            return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()


def spawn_detached_claude_resume(
    argv: Sequence[str],
    *,
    checkout: Path,
    environment: Mapping[str, str],
    attempt_id: str,
    native_session_id: str,
    binary_source: str,
    lease_id: str = "",
    background_job: Mapping[str, str] | None = None,
    state_dir: Path | None = None,
    process_factory: ProcessFactory = subprocess.Popen,
    clock: Callable[[], float] = time.time,
) -> ClaudeResumeProcess | None:
    """Spawn one resume in its own process group and return immediately."""
    now = clock()
    try:
        directory = _capture_directory(state_dir)
        _cleanup_captures(directory, now=now)
        capture_path, capture = _capture_file(directory, attempt_id)
    except (OSError, TypeError, ValueError):
        return None
    # The native runs under a supervisor rather than directly: the relay poll
    # that starts a resume is gone long before the turn ends, so the only place
    # its exit status can be collected is a process that outlives them both.
    supervised = [
        sys.executable,
        "-m",
        session_relay_resume_watch.__name__,
        "--outcome",
        str(resume_outcome_path(capture_path)),
        "--",
        *(str(value) for value in argv),
    ]
    try:
        process = process_factory(
            supervised,
            cwd=checkout,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=capture,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        capture.close()
        capture_path.unlink(missing_ok=True)
        return None
    capture.close()
    if not record_supervised_native(
        attempt_id,
        process.pid,
        native_session_id=native_session_id,
        supervision_kind="resume",
        capture_path=capture_path,
        lease_id=lease_id,
        state_dir=state_dir,
        now=now,
    ):
        _stop_uncontained(process)
        capture_path.unlink(missing_ok=True)
        resume_outcome_path(capture_path).unlink(missing_ok=True)
        return None
    started_at = datetime.fromtimestamp(now, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return ClaudeResumeProcess(
        process.pid,
        str(argv[0]),
        binary_source,
        capture_path,
        started_at,
        dict(background_job or {}),
    )


__all__ = [
    "CAPTURE_DIRECTORY_NAME",
    "CAPTURE_RETENTION_SECONDS",
    "ClaudeResumeProcess",
    "spawn_detached_claude_resume",
]
