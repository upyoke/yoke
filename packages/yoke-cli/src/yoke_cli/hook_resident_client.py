"""Thin Unix-socket client for ``yoke hook evaluate``."""

from __future__ import annotations

import fcntl
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from yoke_cli.config import machine_config
from yoke_contracts.execution_provenance import collect_execution_provenance
from yoke_contracts.hook_evaluator_protocol import (
    HookClientWallReport,
    HookEvaluatorProtocolError,
    HookEvaluatorRequest,
    receive_frame,
    send_frame,
)


RESIDENT_CONNECT_GRACE_SECONDS = 2.0
_CONNECT_ATTEMPT_SECONDS = 0.1
_START_RETRY_SECONDS = 0.025
_SOCKET_PATH_LIMIT_BYTES = 100


@dataclass(frozen=True)
class ResidentPaths:
    state_dir: Path
    socket: Path
    lock: Path
    log: Path


@dataclass(frozen=True)
class ResidentEvaluation:
    stdout: str
    stderr: str
    exit_code: int


class ResidentUnavailable(RuntimeError):
    """The resident could not safely answer this hook invocation."""

    def __init__(self, code: str, detail: str, *, log_path: Path) -> None:
        self.code = code
        self.detail = detail
        self.log_path = log_path
        super().__init__(f"{code}: {detail}")


def resident_paths() -> ResidentPaths:
    state_dir = machine_config.cache_dir() / "hook-evaluator"
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        state_dir.chmod(0o700)
    except OSError:
        pass
    candidate = state_dir / "evaluator.sock"
    if len(os.fsencode(candidate)) > _SOCKET_PATH_LIMIT_BYTES:
        digest = hashlib.sha256(os.fsencode(state_dir)).hexdigest()[:16]
        candidate = Path(tempfile.gettempdir()) / (
            f"yoke-hook-{os.getuid()}-{digest}.sock"
        )
    return ResidentPaths(
        state_dir=state_dir,
        socket=candidate,
        lock=state_dir / "evaluator.lock",
        log=state_dir / "evaluator.log",
    )


def _result_timeout_seconds(environment: dict[str, str]) -> float:
    raw = environment.get("YOKE_HOOK_TOTAL_TIMEOUT_MS", "").strip()
    try:
        timeout_ms = int(raw) if raw else 10000
    except ValueError:
        timeout_ms = 10000
    return max(1.0, timeout_ms / 1000.0 + 2.0)


def _request(
    event_name: str,
    stdin_data: str,
    dry_run: bool,
    client_timing_id: str,
) -> HookEvaluatorRequest:
    return HookEvaluatorRequest(
        event_name=event_name,
        stdin=stdin_data,
        dry_run=dry_run,
        pid=os.getpid(),
        ppid=os.getppid(),
        cwd=os.getcwd(),
        environment=dict(os.environ),
        revision=str(collect_execution_provenance().get("source_sha") or "unknown"),
        client_timing_id=client_timing_id,
    )


def _round_trip(
    paths: ResidentPaths,
    request: HookEvaluatorRequest,
    *,
    client_started_monotonic: float | None = None,
) -> dict:
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        peer.settimeout(_CONNECT_ATTEMPT_SECONDS)
        peer.connect(str(paths.socket))
        peer.settimeout(_result_timeout_seconds(request.environment))
        send_frame(peer, request.to_mapping())
        response = receive_frame(peer)
        if (
            response.get("status") == "ok"
            and request.client_timing_id
            and client_started_monotonic is not None
        ):
            report = HookClientWallReport(
                event_id=request.client_timing_id,
                client_wall_ms=max(
                    0, int((time.monotonic() - client_started_monotonic) * 1000)
                ),
            )
            try:
                send_frame(peer, report.to_mapping())
            except (HookEvaluatorProtocolError, OSError, socket.timeout):
                pass
        return response
    finally:
        peer.close()


def _open_start_lock(path: Path) -> int | None:
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    os.set_inheritable(descriptor, True)
    return descriptor


def _start_resident(paths: ResidentPaths, environment: dict[str, str]) -> None:
    lock_fd = _open_start_lock(paths.lock)
    if lock_fd is None:
        return
    log_fd = -1
    try:
        log_fd = os.open(paths.log, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "yoke_harness.hook_resident",
                "--socket",
                str(paths.socket),
                "--lock-fd",
                str(lock_fd),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=log_fd,
            cwd=str(paths.state_dir),
            env=environment,
            close_fds=True,
            pass_fds=(lock_fd,),
            start_new_session=True,
        )
    except OSError as exc:
        raise ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_UNREACHABLE",
            f"resident start failed ({type(exc).__name__})",
            log_path=paths.log,
        ) from None
    finally:
        if log_fd >= 0:
            os.close(log_fd)
        os.close(lock_fd)


def _validated_result(response: dict, paths: ResidentPaths) -> ResidentEvaluation:
    if response.get("status") == "error":
        code = str(response.get("code") or "YOKE_HOOK_RESIDENT_CRASHED")
        detail = str(response.get("detail") or "resident evaluation failed")
        raise ResidentUnavailable(code, detail, log_path=paths.log)
    if response.get("status") != "ok":
        raise ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_PROTOCOL_ERROR",
            "resident response has no recognized status",
            log_path=paths.log,
        )
    stdout = response.get("stdout")
    stderr = response.get("stderr")
    exit_code = response.get("exit_code")
    if (
        not isinstance(stdout, str)
        or not isinstance(stderr, str)
        or not isinstance(exit_code, int)
    ):
        raise ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_PROTOCOL_ERROR",
            "resident response is not the hook result contract",
            log_path=paths.log,
        )
    return ResidentEvaluation(stdout=stdout, stderr=stderr, exit_code=exit_code)


def evaluate_with_resident(
    event_name: str,
    stdin_data: str,
    *,
    dry_run: bool = False,
    client_timing_id: str = "",
    client_started_monotonic: float | None = None,
) -> ResidentEvaluation:
    """Evaluate through the resident or raise a named fallback reason."""
    paths = resident_paths()
    request = _request(event_name, stdin_data, dry_run, client_timing_id)
    started = time.monotonic()
    start_attempted = False
    last_error = "socket is unreachable"
    while time.monotonic() - started < RESIDENT_CONNECT_GRACE_SECONDS:
        try:
            response = _round_trip(
                paths,
                request,
                client_started_monotonic=client_started_monotonic,
            )
        except HookEvaluatorProtocolError as exc:
            raise ResidentUnavailable(
                "YOKE_HOOK_RESIDENT_PROTOCOL_ERROR",
                str(exc),
                log_path=paths.log,
            ) from None
        except (ConnectionError, OSError, socket.timeout) as exc:
            last_error = f"socket unavailable ({type(exc).__name__})"
            if not start_attempted:
                _start_resident(paths, request.environment)
                start_attempted = True
            time.sleep(_START_RETRY_SECONDS)
            continue
        if response.get("status") == "restart":
            last_error = "resident is re-executing for the installed revision"
            time.sleep(_START_RETRY_SECONDS)
            continue
        return _validated_result(response, paths)
    raise ResidentUnavailable(
        "YOKE_HOOK_RESIDENT_UNREACHABLE",
        last_error,
        log_path=paths.log,
    )


__all__ = [
    "RESIDENT_CONNECT_GRACE_SECONDS",
    "ResidentEvaluation",
    "ResidentPaths",
    "ResidentUnavailable",
    "evaluate_with_resident",
    "resident_paths",
]
