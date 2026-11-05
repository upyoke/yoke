"""Bounded JSON-RPC client for one ``codex app-server --stdio`` exchange."""

from __future__ import annotations

from yoke_harness.session_launch_admission import spawn_admitted_process

import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import threading
import time
from typing import IO, Any

from yoke_contracts.self_host_bootstrap_output import redact_api_tokens
from yoke_harness.session_relay_codex import NativePhase
from yoke_harness.session_relay_codex_app_server_errors import (
    CodexAppServerError,
    rpc_error,
)
from yoke_cli.config.session_relay_instance import strip_relay_owned_python_state

# Imported from where it is defined rather than from the inventory module
# that re-exports it: inventory reads plan limits, and a plan-limit probe
# that reaches this client would otherwise close an import cycle.
from yoke_harness.session_relay_surface_probes import resolve_native_cli


_MAX_LINE_BYTES = 4 * 1024 * 1024
# Enough of a failing child's stderr to name the refusal without turning a
# log line into a transcript.
_STDERR_TAIL_BYTES = 2048
_TURN_OWNER_SECONDS = 24 * 60 * 60
# The vendor method names the phase, so an exchange never has to be told
# where it is.
_METHOD_PHASES: dict[str, NativePhase] = {
    "thread/start": "thread_open",
    "thread/name/set": "thread_open",
    "thread/read": "thread_open",
    "thread/resume": "thread_open",
    "turn/start": "turn_start",
    "turn/steer": "turn_start",
}


class _Client:
    def __init__(
        self,
        binary: str,
        checkout: Path,
        env: dict[str, str],
        timeout: float,
        *,
        capture_stderr: bool = False,
    ) -> None:
        resolved = resolve_native_cli(binary)
        if not resolved or not checkout.is_dir():
            raise CodexAppServerError(
                "app-server unavailable", "binary_resolve", code="binary_resolve"
            )
        self.timeout = timeout
        self.next_id = 1
        self.buffer = bytearray()
        # A temporary file rather than a pipe: nothing reads the child's
        # stderr until the exchange fails, and an unread pipe would block a
        # chatty child part-way through a turn that can run for hours.
        self.stderr_file: IO[bytes] | None = (
            tempfile.TemporaryFile() if capture_stderr else None
        )
        try:
            self.process = spawn_admitted_process(
                [resolved, "app-server", "--stdio"],
                cwd=checkout,
                env=strip_relay_owned_python_state(env),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr_file or subprocess.DEVNULL,
                bufsize=0,
                start_new_session=True,
            )
        except OSError as exc:
            raise CodexAppServerError(
                f"app-server unavailable: {type(exc).__name__}", "spawn", code="spawn"
            ) from exc
        try:
            if self.process.stdin is None or self.process.stdout is None:
                raise CodexAppServerError(
                    "app-server pipes unavailable", "spawn", code="pipes"
                )
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            self.request(
                "initialize",
                {"clientInfo": {"name": "yoke_session_relay", "version": "1"}},
            )
            self.notify("initialized", {})
        except BaseException:
            # No caller holds a client yet, so nobody else can stop the child.
            self.close()
            raise

    def _send(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
        if len(body) > _MAX_LINE_BYTES or self.process.stdin is None:
            raise CodexAppServerError(
                "app-server request rejected", code="request_rejected"
            )
        try:
            self.process.stdin.write(body)
            self.process.stdin.flush()
        except OSError as exc:
            raise CodexAppServerError(
                f"app-server request write failed: {type(exc).__name__}",
                code="write_failed",
            ) from exc

    def _line(self, deadline: float) -> bytes:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self.buffer[:newline])
                del self.buffer[: newline + 1]
                return line
            if len(self.buffer) > _MAX_LINE_BYTES:
                raise CodexAppServerError(
                    "app-server response exceeded limit", code="response_oversize"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise CodexAppServerError(
                    "app-server response timed out", code="timeout"
                )
            if self.process.stdout is None:
                raise CodexAppServerError(
                    "app-server response unavailable", code="stdout_unavailable"
                )
            chunk = os.read(self.process.stdout.fileno(), 65_536)
            if not chunk:
                raise CodexAppServerError(
                    "app-server exited before replying", code="eof"
                )
            self.buffer.extend(chunk)

    def _receive(self, deadline: float) -> dict[str, Any]:
        while True:
            try:
                payload = json.loads(self._line(deadline))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return payload

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Exchange one request, bounding the whole call by its own deadline.

        The deadline covers the loop and not only each read, because a peer
        that keeps sending unrelated traffic can otherwise hold the caller
        here forever without a single blocking wait.
        """
        phase = _METHOD_PHASES.get(method, "handshake")
        request_id = self.next_id
        self.next_id += 1
        try:
            self._send({"method": method, "id": request_id, "params": params})
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                payload = self._receive(deadline)
                if payload.get("id") == request_id and "method" not in payload:
                    if "error" in payload:
                        raise rpc_error(method, phase, payload.get("error"))
                    result = payload.get("result")
                    return result if isinstance(result, dict) else {}
                if "method" in payload and "id" in payload:
                    self._send(
                        {
                            "id": payload["id"],
                            "error": {
                                "code": -32601,
                                "message": "unsupported request",
                            },
                        }
                    )
        except CodexAppServerError as exc:
            raise CodexAppServerError(
                str(exc), phase, code=exc.code, rpc_error_code=exc.rpc_error_code
            ) from exc
        raise CodexAppServerError(f"{method} timed out", phase, code="timeout")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def detach_until_turn_completed(self, turn_id: str) -> None:
        def drain() -> None:
            deadline = time.monotonic() + _TURN_OWNER_SECONDS
            try:
                while time.monotonic() < deadline:
                    payload = self._receive(deadline)
                    if payload.get("method") != "turn/completed":
                        continue
                    params = payload.get("params")
                    turn = params.get("turn") if isinstance(params, dict) else None
                    completed = turn.get("id") if isinstance(turn, dict) else None
                    if completed == turn_id:
                        break
            except Exception:
                pass
            finally:
                self.close()

        threading.Thread(
            target=drain, daemon=False, name="yoke-codex-app-server-reap"
        ).start()

    def stderr_tail(self) -> str:
        """The last bytes the child wrote, or empty when capture is off."""
        if self.stderr_file is None:
            return ""
        try:
            self.stderr_file.seek(0, os.SEEK_END)
            self.stderr_file.seek(max(0, self.stderr_file.tell() - _STDERR_TAIL_BYTES))
            text = self.stderr_file.read().decode("utf-8", "replace").strip()
            return redact_api_tokens(text)
        except (OSError, ValueError):
            return ""

    def close(self) -> None:
        try:
            self.selector.close()
        except Exception:
            pass
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if self.stderr_file is not None:
            try:
                self.stderr_file.close()
            except OSError:
                pass


__all__ = ["CodexAppServerError"]
