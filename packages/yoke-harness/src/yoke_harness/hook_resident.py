"""Warm, machine-local evaluator behind ``yoke hook evaluate``."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import socketserver
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from yoke_contracts.execution_provenance import collect_execution_provenance
from yoke_contracts.hook_evaluator_protocol import (
    HookEvaluatorProtocolError,
    HookEvaluatorRequest,
    RESIDENT_IDLE_TIMEOUT_SECONDS,
    receive_frame,
    send_frame,
)
from yoke_contracts.hook_process_context import (
    HookProcessContext,
    activate_process_context,
    install_process_context,
)
from yoke_contracts.hook_resident_routing import (
    is_read_only_tool_event,
    message_probe_key,
)


_UNKNOWN_REVISIONS = frozenset({"", "unknown"})
_SERVER_POLL_SECONDS = 0.25


def _same_revision(left: str, right: str) -> bool:
    left = left.strip().lower()
    right = right.strip().lower()
    if left in _UNKNOWN_REVISIONS or right in _UNKNOWN_REVISIONS:
        return True
    return left == right or left.startswith(right) or right.startswith(left)


class _ResidentServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = True

    def __init__(self, socket_path: str, lock_fd: int) -> None:
        install_process_context()
        from yoke_harness.hook_resident_http import ResidentHttpOpener
        from yoke_harness.hook_resident_observations import ObservationQueue

        self.socket_path = socket_path
        self.lock_fd = lock_fd
        self.loaded_revision = str(
            collect_execution_provenance().get("source_sha") or "unknown"
        )
        self.started_at = time.monotonic()
        self.last_activity = self.started_at
        self.active_requests = 0
        self.state_lock = threading.Lock()
        self.probe_lock = threading.Lock()
        self.last_message_probes: dict[str, float] = {}
        self.stop_event = threading.Event()
        self.restart_event = threading.Event()
        self.http_opener = ResidentHttpOpener()
        self.observations = ObservationQueue(self.http_opener)
        # Preload the canonical evaluator only after process facades exist.
        from yoke_cli.commands.adapters.hook_inprocess import evaluate_inprocess

        self.evaluate_inprocess = evaluate_inprocess
        super().__init__(socket_path, _ResidentHandler)
        self.timeout = _SERVER_POLL_SECONDS

    def begin_request(self) -> None:
        with self.state_lock:
            self.active_requests += 1
            self.last_activity = time.monotonic()

    def end_request(self) -> None:
        with self.state_lock:
            self.active_requests = max(0, self.active_requests - 1)
            self.last_activity = time.monotonic()

    def idle_expired(self) -> bool:
        with self.state_lock:
            idle = self.active_requests == 0 and (
                time.monotonic() - self.last_activity
                >= RESIDENT_IDLE_TIMEOUT_SECONDS
            )
        return idle and self.observations.pending_count() == 0

    def should_evaluate_locally(self, session_id: str) -> bool:
        if not session_id:
            return False
        from yoke_harness.hook_resident_observations import (
            MESSAGE_PROBE_INTERVAL_SECONDS,
        )

        with self.probe_lock:
            last = self.last_message_probes.get(session_id)
        return last is not None and (
            time.monotonic() - last < MESSAGE_PROBE_INTERVAL_SECONDS
        )

    def mark_message_probe(self, session_id: str) -> None:
        if not session_id:
            return
        with self.probe_lock:
            self.last_message_probes[session_id] = time.monotonic()

    def evaluate(self, request: HookEvaluatorRequest) -> dict[str, Any]:
        if not os.path.isabs(request.cwd) or not os.path.isdir(request.cwd):
            return {
                "status": "error",
                "code": "YOKE_HOOK_RESIDENT_CONTEXT_INVALID",
                "detail": "caller cwd is unavailable; retry from an existing directory",
            }
        process = HookProcessContext(
            environment=dict(request.environment),
            cwd=request.cwd,
            pid=request.pid,
            ppid=request.ppid,
        )
        read_only = is_read_only_tool_event(request.event_name, request.stdin)
        probe_key = message_probe_key(request.stdin)
        local = read_only and self.should_evaluate_locally(probe_key)
        started = time.monotonic()
        with activate_process_context(process) as capture:
            from yoke_cli.commands.adapters.hook_config_dedup import (
                is_cursor_config_invocation,
            )

            deferred = None
            opener = self.http_opener
            if local:
                from yoke_harness.hook_resident_observations import (
                    DeferredObservationOpener,
                )

                deferred = DeferredObservationOpener()
                opener = deferred
            exit_code = self.evaluate_inprocess(
                request.event_name,
                request.stdin,
                dry_run=request.dry_run,
                cursor_invocation=is_cursor_config_invocation(
                    request.environment, request.stdin
                ),
                http_opener=opener,
                evaluator="resident",
                warm_duration_ms=int((time.monotonic() - self.started_at) * 1000),
            )
            hook_wait_ms = int((time.monotonic() - started) * 1000)
            if deferred is not None:
                self.observations.enqueue(
                    deferred.observation(hook_wait_ms=hook_wait_ms)
                )
            elif read_only:
                self.mark_message_probe(probe_key)
            stdout = capture.stdout
            stderr = capture.stderr + self.observations.diagnostic()
        return {
            "status": "ok",
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": int(exit_code),
        }


class _ResidentHandler(socketserver.BaseRequestHandler):
    server: _ResidentServer

    def handle(self) -> None:
        self.server.begin_request()
        try:
            self.request.settimeout(15.0)
            try:
                request = HookEvaluatorRequest.from_mapping(receive_frame(self.request))
                if not _same_revision(request.revision, self.server.loaded_revision):
                    send_frame(self.request, {"status": "restart"})
                    self.server.restart_event.set()
                    return
                response = self.server.evaluate(request)
            except HookEvaluatorProtocolError as exc:
                response = {
                    "status": "error",
                    "code": "YOKE_HOOK_RESIDENT_PROTOCOL_ERROR",
                    "detail": str(exc),
                }
            except Exception as exc:  # client falls back to canonical in-process
                traceback.print_exc()
                response = {
                    "status": "error",
                    "code": "YOKE_HOOK_RESIDENT_CRASHED",
                    "detail": f"resident evaluation crashed ({type(exc).__name__})",
                }
            try:
                send_frame(self.request, response)
            except (HookEvaluatorProtocolError, OSError, socket.timeout):
                pass
        finally:
            self.server.end_request()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yoke resident hook evaluator")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--lock-fd", required=True, type=int)
    return parser.parse_args()


def _unlink_socket(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _serve(socket_path: Path, lock_fd: int) -> bool:
    _unlink_socket(socket_path)
    server = _ResidentServer(str(socket_path), lock_fd)
    socket_path.chmod(0o600)

    def stop(_signum=None, _frame=None) -> None:
        server.stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    restart = False
    try:
        while not server.stop_event.is_set():
            if server.restart_event.is_set():
                if server.observations.pending_count() == 0:
                    restart = True
                    break
                server.observations.drain(0.5)
            if server.idle_expired():
                break
            server.handle_request()
    finally:
        server.server_close()
        drained = server.observations.close(drain_timeout=2.0)
        if not drained:
            sys.stderr.write(
                "ERROR: YOKE_HOOK_TELEMETRY_DRAIN_TIMEOUT: retained observations "
                "could not flush before resident shutdown\n"
            )
        server.http_opener.close()
        _unlink_socket(socket_path)
    return restart and drained


def main() -> int:
    args = _parse_args()
    socket_path = Path(args.socket)
    try:
        os.fstat(args.lock_fd)
    except OSError:
        sys.stderr.write(
            "ERROR: YOKE_HOOK_RESIDENT_LOCK_INVALID: start through "
            "`yoke hook evaluate` so the singleton lock is inherited\n"
        )
        return 2
    os.set_inheritable(args.lock_fd, True)
    socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not _serve(socket_path, args.lock_fd):
        os.close(args.lock_fd)
        return 0
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "yoke_harness.hook_resident",
            "--socket",
            str(socket_path),
            "--lock-fd",
            str(args.lock_fd),
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
