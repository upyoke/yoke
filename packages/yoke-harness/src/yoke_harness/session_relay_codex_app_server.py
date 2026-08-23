"""Bounded Codex app-server transport for desktop-backed relay tasks."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest
from yoke_harness.session_relay_codex_cli import _launch_environment


_MAX_LINE_BYTES = 4 * 1024 * 1024
_TURN_OWNER_SECONDS = 24 * 60 * 60
_RESUMABLE_NATIVE_STATUSES = frozenset({"idle", "notLoaded"})
_CLIENT_MESSAGE_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://upyoke.com/session-relay/codex-client-message",
)


class CodexAppServerError(RuntimeError):
    """The bounded app-server exchange could not prove its outcome."""


class _Client:
    def __init__(
        self,
        binary: str,
        checkout: Path,
        env: dict[str, str],
        timeout: float,
    ) -> None:
        resolved = shutil.which(binary) if os.sep not in binary else binary
        if not resolved or not checkout.is_dir():
            raise CodexAppServerError("app-server unavailable")
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
            raise CodexAppServerError("app-server unavailable") from exc
        if self.process.stdin is None or self.process.stdout is None:
            raise CodexAppServerError("app-server pipes unavailable")
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
        request_id = self.next_id
        self.next_id += 1
        self._send({"method": method, "id": request_id, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            payload = self._receive(deadline)
            if payload.get("id") == request_id and "method" not in payload:
                if "error" in payload:
                    raise CodexAppServerError(f"{method} failed")
                result = payload.get("result")
                return result if isinstance(result, dict) else {}
            if "method" in payload and "id" in payload:
                self._send(
                    {
                        "id": payload["id"],
                        "error": {"code": -32601, "message": "unsupported request"},
                    }
                )

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


def _thread(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("thread")
    if not isinstance(value, dict):
        raise CodexAppServerError("thread response missing identity")
    return value


def _identity(value: dict[str, Any]) -> tuple[str, str]:
    thread_id = str(value.get("id") or "").strip()
    session_id = str(value.get("sessionId") or "").strip()
    if not thread_id or not session_id:
        raise CodexAppServerError("thread response missing identity")
    return thread_id, session_id


def _text_input(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": value, "text_elements": []}]


def _turn_id(result: dict[str, Any]) -> str:
    turn = result.get("turn")
    value = turn.get("id") if isinstance(turn, dict) else None
    if not isinstance(value, str) or not value:
        raise CodexAppServerError("turn response missing identity")
    return value


def _client_message_id(request: CodexNativeRequest, thread_id: str) -> str:
    if not request.instruction_id:
        raise CodexAppServerError("instruction identity missing")
    return str(
        uuid.uuid5(
            _CLIENT_MESSAGE_NAMESPACE,
            f"{request.instruction_id}:thread:{thread_id}",
        )
    )


def _start_turn(client: _Client, thread_id: str, request: CodexNativeRequest) -> str:
    return _turn_id(
        client.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": _text_input(request.native_instruction),
                "clientUserMessageId": _client_message_id(request, thread_id),
            },
        )
    )


class CodexAppServerTransport:
    """Official desktop create and liveness-keyed wake primitives."""

    def __init__(
        self,
        *,
        binary: str = "codex",
        timeout: float = 30.0,
        worker: bool = False,
    ) -> None:
        self.binary = binary
        self.timeout = timeout
        self.worker = worker

    @staticmethod
    def _detached(request: CodexNativeRequest) -> CodexNativeOutcome:
        from yoke_harness.session_relay_codex_app_server_process import (
            run_detached_operation,
        )

        return run_detached_operation(request)

    def _client(self, request: CodexNativeRequest) -> _Client:
        return _Client(
            self.binary,
            request.checkout,
            _launch_environment(request),
            self.timeout,
        )

    def create(self, request: CodexNativeRequest) -> CodexNativeOutcome:
        if not self.worker:
            return self._detached(request)
        client: _Client | None = None
        created = False
        try:
            client = self._client(request)
            params: dict[str, Any] = {
                "cwd": str(request.checkout.resolve()),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "serviceName": request.presentation or "yoke_session_relay",
            }
            if request.requested_model:
                params["model"] = request.requested_model
            identity = _identity(_thread(client.request("thread/start", params)))
            created = True
            if identity[0] != identity[1]:
                raise CodexAppServerError("thread/session identity mismatch")
            turn_id = _start_turn(client, identity[0], request)
            client.detach_until_turn_completed(turn_id)
            return CodexNativeOutcome("accepted", identity[0], identity_correlated=True)
        except CodexAppServerError:
            if client is not None:
                client.close()
            return CodexNativeOutcome("outcome_unknown" if created else "not_created")

    def wake(self, request: CodexNativeRequest) -> CodexNativeOutcome:
        if not request.target_session_id:
            return CodexNativeOutcome("unsupported_surface")
        if not self.worker:
            return self._detached(request)
        client: _Client | None = None
        mutated = False
        try:
            client = self._client(request)
            target_session_id = str(request.target_session_id)
            try:
                current = _thread(
                    client.request(
                        "thread/read",
                        {"threadId": target_session_id, "includeTurns": True},
                    )
                )
            except CodexAppServerError:
                # Resume is also the exact existence check when an unloaded
                # thread cannot be read by a fresh app-server process.
                current = None
            if current is None:
                identity = (target_session_id, target_session_id)
                native_status = "notLoaded"
            else:
                identity = _identity(current)
                if identity != (target_session_id, target_session_id):
                    raise CodexAppServerError("thread/session identity mismatch")
                status = current.get("status")
                native_status = status.get("type") if isinstance(status, dict) else None
            if native_status == "active":
                active = [
                    turn
                    for turn in current.get("turns", [])
                    if isinstance(turn, dict) and turn.get("status") == "inProgress"
                ]
                if len(active) != 1 or not isinstance(active[0].get("id"), str):
                    client.close()
                    return CodexNativeOutcome("outcome_unknown")
                turn_id = str(active[0]["id"])
                mutated = True
                client.request(
                    "turn/steer",
                    {
                        "threadId": identity[0],
                        "expectedTurnId": turn_id,
                        "input": _text_input(request.native_instruction),
                        "clientUserMessageId": _client_message_id(request, identity[0]),
                    },
                )
            elif native_status in _RESUMABLE_NATIVE_STATUSES:
                resumed = _identity(
                    _thread(client.request("thread/resume", {"threadId": identity[0]}))
                )
                if resumed != identity:
                    raise CodexAppServerError("resumed identity mismatch")
                mutated = True
                turn_id = _start_turn(client, identity[0], request)
            else:
                client.close()
                return CodexNativeOutcome("outcome_unknown")
            client.detach_until_turn_completed(turn_id)
            return CodexNativeOutcome("accepted", identity[0], identity_correlated=True)
        except CodexAppServerError:
            if client is not None:
                client.close()
            return CodexNativeOutcome("outcome_unknown" if mutated else "not_found")


__all__ = [
    "CodexAppServerError",
    "CodexAppServerTransport",
]
