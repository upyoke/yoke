"""Thin Unix-socket client for ``yoke hook evaluate``."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from yoke_cli import hook_resident_paths as _resident_paths
from yoke_contracts import platform_file_lock
from yoke_contracts.hook_budget import TOTAL_TIMEOUT_ENV, hook_budget_ms
from yoke_contracts.execution_provenance import collect_execution_provenance
from yoke_contracts.hook_evaluator_protocol import (
    HookClientWallReport,
    HookEvaluatorProtocolError,
    HookEvaluatorRequest,
    receive_frame,
    send_frame,
)


ResidentPaths = _resident_paths.ResidentPaths
resident_paths = _resident_paths.resident_paths
resident_transport_available = _resident_paths.resident_transport_available
resident_transport_refusal = _resident_paths.resident_transport_refusal
# Compatibility seam for lifecycle callers and tests that redirect the cache root.
machine_config = _resident_paths.machine_config


_CONNECT_ATTEMPT_SECONDS = 0.1
_START_RETRY_SECONDS = 0.025
# What the resident keeps back from the caller's remaining budget, so its
# answer arrives before the caller stops listening.
_SETTLEMENT_SECONDS = 0.5


@dataclass(frozen=True)
class ResidentEvaluation:
    stdout: str
    stderr: str
    exit_code: int
    resident_wait_ms: int = 0


class ResidentUnavailable(RuntimeError):
    """The resident could not safely answer this hook invocation."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        log_path: Path,
        resident_wait_ms: int = 0,
    ) -> None:
        self.code = code
        self.detail = detail
        self.log_path = log_path
        self.resident_wait_ms = resident_wait_ms
        super().__init__(f"{code}: {detail}")


def _budget_deadline(
    environment: dict[str, str], client_started_monotonic: float | None
) -> float:
    """When this hook process's budget ends, measured from its own start."""
    started = (
        time.monotonic()
        if client_started_monotonic is None
        else client_started_monotonic
    )
    return started + hook_budget_ms(environment) / 1000.0


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


def _connect(paths: ResidentPaths, deadline: float) -> socket.socket:
    """One connect attempt that never waits past the budget."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise socket.timeout("hook budget is exhausted")
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        peer.settimeout(min(_CONNECT_ATTEMPT_SECONDS, remaining))
        peer.connect(str(paths.socket))
    except BaseException:
        peer.close()
        raise
    return peer


def _exchange(
    peer: socket.socket,
    request: HookEvaluatorRequest,
    deadline: float,
    client_started_monotonic: float | None = None,
) -> dict:
    """Send one request; the resident evaluates inside what is left."""
    remaining = deadline - time.monotonic()
    payload = request.to_mapping()
    payload["environment"] = {
        **request.environment,
        TOTAL_TIMEOUT_ENV: str(max(1, int((remaining - _SETTLEMENT_SECONDS) * 1000))),
    }
    peer.settimeout(max(0.001, remaining))
    send_frame(peer, payload)
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


def _round_trip(
    paths: ResidentPaths,
    request: HookEvaluatorRequest,
    deadline: float,
    client_started_monotonic: float | None = None,
) -> dict:
    peer = _connect(paths, deadline)
    try:
        return _exchange(peer, request, deadline, client_started_monotonic)
    finally:
        peer.close()


def _open_start_lock(path: Path) -> int | None:
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        platform_file_lock.acquire_exclusive_nonblocking(descriptor)
    except BlockingIOError:
        os.close(descriptor)
        return None
    os.set_inheritable(descriptor, True)
    return descriptor


def _start_resident(
    paths: ResidentPaths, environment: dict[str, str]
) -> subprocess.Popen | None:
    """Launch a resident unless another caller holds the start lock."""
    lock_fd = _open_start_lock(paths.lock)
    if lock_fd is None:
        return None
    log_fd = -1
    try:
        log_fd = os.open(paths.log, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        return subprocess.Popen(
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


def _restart_detail(response: dict) -> str:
    """Name both revisions, so a stuck upgrade is readable from one line."""
    loaded = str(response.get("loaded_revision") or "unknown")[:12]
    requested = str(response.get("requested_revision") or "unknown")[:12]
    return (
        "resident is re-executing for the installed revision "
        f"(loaded {loaded}, requested {requested})"
    )


def _validated_result(
    response: dict,
    paths: ResidentPaths,
    resident_wait_ms: int = 0,
) -> ResidentEvaluation:
    if response.get("status") == "error":
        code = str(response.get("code") or "YOKE_HOOK_RESIDENT_CRASHED")
        detail = str(response.get("detail") or "resident evaluation failed")
        raise ResidentUnavailable(
            code, detail, log_path=paths.log, resident_wait_ms=resident_wait_ms
        )
    if response.get("status") != "ok":
        raise ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_PROTOCOL_ERROR",
            "resident response has no recognized status",
            log_path=paths.log,
            resident_wait_ms=resident_wait_ms,
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
            resident_wait_ms=resident_wait_ms,
        )
    return ResidentEvaluation(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        resident_wait_ms=resident_wait_ms,
    )


def evaluate_with_resident(
    event_name: str,
    stdin_data: str,
    *,
    dry_run: bool = False,
    client_timing_id: str = "",
    client_started_monotonic: float | None = None,
) -> ResidentEvaluation:
    """Evaluate through the resident inside the hook budget, or raise why not.

    The resident listens before it loads the evaluator, so a cold one is
    reachable at once: the caller waits on it rather than loading a second
    evaluator beside it. A launched resident that exits before listening
    ends the wait at once.
    """
    paths = resident_paths()
    refusal = resident_transport_refusal(paths)
    if refusal is not None:
        raise ResidentUnavailable(*refusal, log_path=paths.log)
    request = _request(event_name, stdin_data, dry_run, client_timing_id)
    deadline = _budget_deadline(request.environment, client_started_monotonic)
    started = time.monotonic()
    launched: subprocess.Popen | None = None
    start_attempted = False
    last_error = "socket is unreachable"

    def waited_ms() -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    def unavailable(code: str, detail: str) -> ResidentUnavailable:
        return ResidentUnavailable(
            code, detail, log_path=paths.log, resident_wait_ms=waited_ms()
        )

    while True:
        try:
            peer = _connect(paths, deadline)
        except OSError as exc:
            last_error = f"socket unavailable ({type(exc).__name__})"
            if not start_attempted:
                launched = _start_resident(paths, request.environment)
                start_attempted = True
            elif launched is not None and launched.poll() is not None:
                raise unavailable(
                    "YOKE_HOOK_RESIDENT_START_FAILED",
                    f"resident exited with status {launched.returncode} "
                    "before it listened",
                ) from None
        else:
            try:
                response = _exchange(peer, request, deadline, client_started_monotonic)
            except HookEvaluatorProtocolError as exc:
                raise unavailable("YOKE_HOOK_RESIDENT_PROTOCOL_ERROR", str(exc)) from None
            except socket.timeout:
                raise unavailable(
                    "YOKE_HOOK_RESIDENT_TIMEOUT",
                    "resident did not answer inside the hook budget",
                ) from None
            except OSError as exc:
                # A resident closing for an upgrade resets queued callers.
                response = {}
                last_error = f"resident connection reset ({type(exc).__name__})"
            finally:
                peer.close()
            if response and response.get("status") != "restart":
                return _validated_result(response, paths, waited_ms())
            if response:
                last_error = _restart_detail(response)
        # Every retry is spent inside the budget, so a resident that keeps
        # answering "restart" cannot amplify into an unbounded wait.
        if deadline - time.monotonic() <= _START_RETRY_SECONDS:
            raise unavailable("YOKE_HOOK_RESIDENT_UNREACHABLE", last_error)
        time.sleep(_START_RETRY_SECONDS)


__all__ = [
    "ResidentEvaluation",
    "ResidentPaths",
    "ResidentUnavailable",
    "evaluate_with_resident",
    "resident_paths",
    "resident_transport_available",
    "resident_transport_refusal",
]
