"""Bounded Cursor ACP transport for exact idle-session prompting."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import threading
import time
from typing import Any
from uuid import UUID

from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_cursor import (
    CursorCreateRequest,
    CursorNativeResult,
    CursorWakeRequest,
)


CURSOR_ACP_TIMEOUT_SECONDS = 20.0
CURSOR_ACP_TURN_SECONDS = 120.0
_MAX_LINE_BYTES = 4 * 1024 * 1024


class CursorAcpError(RuntimeError):
    """The closed ACP exchange could not prove its requested boundary."""


def _environment(request: CursorCreateRequest | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["YOKE_EXECUTOR"] = "cursor"
    env["CURSOR_INVOKED_AS"] = "cursor-agent"
    if request is not None:
        env[LAUNCH_CONTEXT_ENV] = json.dumps(
            {
                "launch_id": request.launch_id,
                "attestation": request.launch_attestation,
            },
            separators=(",", ":"),
        )
    return env


def _session_id(value: object) -> str | None:
    try:
        return str(UUID(str(value or "").strip()))
    except (AttributeError, TypeError, ValueError):
        return None


def _session_params(checkout: Path) -> dict[str, object]:
    return {"cwd": str(checkout.resolve()), "mcpServers": []}


def _prompt_params(session_id: str, instruction: str) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "prompt": [{"type": "text", "text": instruction}],
    }


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
            raise CursorAcpError("ACP unavailable")
        self.timeout = timeout
        self.next_id = 1
        self.buffer = bytearray()
        try:
            self.process = subprocess.Popen(
                [resolved, "acp"],
                cwd=checkout,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                start_new_session=True,
            )
        except OSError as exc:
            raise CursorAcpError("ACP unavailable") from exc
        if self.process.stdin is None or self.process.stdout is None:
            self.process.terminate()
            raise CursorAcpError("ACP pipes unavailable")
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def _send(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
        if len(body) > _MAX_LINE_BYTES or self.process.stdin is None:
            raise CursorAcpError("ACP request refused")
        try:
            self.process.stdin.write(body)
            self.process.stdin.flush()
        except OSError as exc:
            raise CursorAcpError("ACP request failed") from exc

    def _line(self, deadline: float) -> bytes:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self.buffer[:newline])
                del self.buffer[: newline + 1]
                return line
            if len(self.buffer) > _MAX_LINE_BYTES:
                raise CursorAcpError("ACP response exceeded limit")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise CursorAcpError("ACP response timed out")
            if self.process.stdout is None:
                raise CursorAcpError("ACP response unavailable")
            chunk = os.read(self.process.stdout.fileno(), 65_536)
            if not chunk:
                raise CursorAcpError("ACP exited")
            self.buffer.extend(chunk)

    def _receive(self, deadline: float) -> dict[str, Any]:
        while True:
            try:
                payload = json.loads(self._line(deadline))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return payload

    def _answer_agent_request(self, payload: dict[str, Any]) -> None:
        request_id = payload.get("id")
        method = payload.get("method")
        if request_id is None:
            return
        if method in {
            "session/request_permission",
            "cursor/ask_question",
            "cursor/create_plan",
        }:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"outcome": {"outcome": "cancelled"}},
                }
            )
            return
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "unsupported request"},
            }
        )

    def _request_id(self, method: str, params: dict[str, object]) -> int:
        request_id = self.next_id
        self.next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        return request_id

    def request(self, method: str, params: dict[str, object]) -> dict[str, Any]:
        request_id = self._request_id(method, params)
        deadline = time.monotonic() + self.timeout
        while True:
            payload = self._receive(deadline)
            if payload.get("id") == request_id and "method" not in payload:
                if "error" in payload:
                    raise CursorAcpError(f"{method} refused")
                result = payload.get("result")
                return result if isinstance(result, dict) else {}
            if "method" in payload and "id" in payload:
                self._answer_agent_request(payload)

    def start_prompt(self, session_id: str, instruction: str) -> None:
        request_id = self._request_id(
            "session/prompt", _prompt_params(session_id, instruction)
        )

        def drain() -> None:
            deadline = time.monotonic() + CURSOR_ACP_TURN_SECONDS
            try:
                while time.monotonic() < deadline:
                    payload = self._receive(deadline)
                    if payload.get("id") == request_id and "method" not in payload:
                        break
                    if "method" in payload and "id" in payload:
                        self._answer_agent_request(payload)
            except Exception:
                pass
            finally:
                self.close()

        threading.Thread(
            target=drain,
            daemon=True,
            name="yoke-cursor-acp-reap",
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


class CursorAcpTransport:
    """Use the documented ACP lifecycle without inventing a session lookup."""

    def __init__(self, *, binary: str = "cursor-agent", timeout: float = 20.0) -> None:
        self.binary = binary
        self.timeout = timeout

    def _client(
        self,
        checkout: Path,
        request: CursorCreateRequest | None = None,
    ) -> _Client:
        client = _Client(self.binary, checkout, _environment(request), self.timeout)
        try:
            client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {
                        "name": "yoke_session_relay",
                        "version": "1",
                    },
                },
            )
            client.request("authenticate", {"methodId": "cursor_login"})
            return client
        except CursorAcpError:
            client.close()
            raise

    def new_session(self, request: CursorCreateRequest) -> CursorNativeResult:
        started = time.monotonic()
        client: _Client | None = None
        session_id: str | None = None
        try:
            client = self._client(request.checkout, request)
            result = client.request("session/new", _session_params(request.checkout))
            session_id = _session_id(result.get("sessionId"))
            if session_id is None:
                raise CursorAcpError("session/new identity missing")
            client.start_prompt(session_id, request.native_instruction)
            return CursorNativeResult(
                "native_created",
                native_session_id=session_id,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        except CursorAcpError:
            if client is not None:
                client.close()
            return CursorNativeResult(
                "outcome_unknown" if session_id else "not_created"
            )

    def prompt_session(self, request: CursorWakeRequest) -> CursorNativeResult:
        started = time.monotonic()
        client: _Client | None = None
        loaded = False
        try:
            client = self._client(request.checkout)
            params = _session_params(request.checkout)
            params["sessionId"] = request.target_session_id
            client.request("session/load", params)
            loaded = True
            client.start_prompt(request.target_session_id, request.native_instruction)
            return CursorNativeResult(
                "accepted",
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
        except CursorAcpError:
            if client is not None:
                client.close()
            return CursorNativeResult("outcome_unknown" if loaded else "not_found")


__all__ = ["CURSOR_ACP_TIMEOUT_SECONDS", "CursorAcpError", "CursorAcpTransport"]
