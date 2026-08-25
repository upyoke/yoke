"""Bounded JSON-RPC client for one ``codex app-server --stdio`` exchange."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import threading
import time
from typing import Any

from yoke_harness.session_relay_codex import NativePhase
from yoke_harness.session_relay_inventory import resolve_native_cli


_MAX_LINE_BYTES = 4 * 1024 * 1024
_TURN_OWNER_SECONDS = 24 * 60 * 60
# The vendor method names the phase, so an exchange never has to be told
# where it is.
_METHOD_PHASES: dict[str, NativePhase] = {
    "thread/start": "thread_open",
    "thread/read": "thread_open",
    "thread/resume": "thread_open",
    "turn/start": "turn_start",
    "turn/steer": "turn_start",
}


class CodexAppServerError(RuntimeError):
    """The bounded app-server exchange could not prove its outcome.

    The phase is the point of the failure: an exchange that only says it
    failed leaves a stalled launch attempt with nothing to read.
    """

    def __init__(self, message: str, phase: NativePhase = "handshake") -> None:
        super().__init__(message)
        self.phase = phase


class _Client:
    def __init__(
        self,
        binary: str,
        checkout: Path,
        env: dict[str, str],
        timeout: float,
    ) -> None:
        resolved = resolve_native_cli(binary)
        if not resolved or not checkout.is_dir():
            raise CodexAppServerError("app-server unavailable", "binary_resolve")
        self.timeout = timeout
        self.next_id = 1
        self.buffer = bytearray()
        try:
            self.process = subprocess.Popen(
                [resolved, "app-server", "--stdio"],
                cwd=checkout,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                start_new_session=True,
            )
        except OSError as exc:
            raise CodexAppServerError("app-server unavailable", "spawn") from exc
        if self.process.stdin is None or self.process.stdout is None:
            raise CodexAppServerError("app-server pipes unavailable", "spawn")
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.request(
            "initialize",
            {"clientInfo": {"name": "yoke_session_relay", "version": "1"}},
        )
        self.notify("initialized", {})

    def _send(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
        if len(body) > _MAX_LINE_BYTES or self.process.stdin is None:
            raise CodexAppServerError("app-server request rejected")
        self.process.stdin.write(body)
        self.process.stdin.flush()

    def _line(self, deadline: float) -> bytes:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self.buffer[:newline])
                del self.buffer[: newline + 1]
                return line
            if len(self.buffer) > _MAX_LINE_BYTES:
                raise CodexAppServerError("app-server response exceeded limit")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise CodexAppServerError("app-server response timed out")
            if self.process.stdout is None:
                raise CodexAppServerError("app-server response unavailable")
            chunk = os.read(self.process.stdout.fileno(), 65_536)
            if not chunk:
                raise CodexAppServerError("app-server exited")
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
                        raise CodexAppServerError(f"{method} failed", phase)
                    result = payload.get("result")
                    return result if isinstance(result, dict) else {}
                if "method" in payload and "id" in payload:
                    self._send(
                        {
                            "id": payload["id"],
                            "error": {"code": -32601, "message": "unsupported request"},
                        }
                    )
        except CodexAppServerError as exc:
            raise CodexAppServerError(str(exc), phase) from exc
        raise CodexAppServerError(f"{method} timed out", phase)

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


__all__ = ["CodexAppServerError"]
