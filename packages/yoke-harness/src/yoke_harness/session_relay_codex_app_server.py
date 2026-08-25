"""Bounded Codex app-server transport for desktop-backed relay tasks."""

from __future__ import annotations

import uuid
from typing import Any

from yoke_harness.session_relay_codex import (
    CodexNativeOutcome,
    CodexNativeRequest,
    NativePhase,
)
from yoke_harness.session_relay_codex_app_server_client import (
    CodexAppServerError,
    _Client,
)
from yoke_harness.session_relay_codex_cli import _launch_environment
from yoke_harness.session_relay_inventory import resolve_native_cli_source


_RESUMABLE_NATIVE_STATUSES = frozenset({"idle", "notLoaded"})
_CLIENT_MESSAGE_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://upyoke.com/session-relay/codex-client-message",
)


def _thread(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("thread")
    if not isinstance(value, dict):
        raise CodexAppServerError("thread response missing identity", "thread_open")
    return value


def _identity(value: dict[str, Any]) -> tuple[str, str]:
    thread_id = str(value.get("id") or "").strip()
    session_id = str(value.get("sessionId") or "").strip()
    if not thread_id or not session_id:
        raise CodexAppServerError("thread response missing identity", "thread_open")
    return thread_id, session_id


def _text_input(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": value, "text_elements": []}]


def _turn_id(result: dict[str, Any]) -> str:
    turn = result.get("turn")
    value = turn.get("id") if isinstance(turn, dict) else None
    if not isinstance(value, str) or not value:
        raise CodexAppServerError("turn response missing identity", "turn_start")
    return value


def _client_message_id(request: CodexNativeRequest, thread_id: str) -> str:
    if not request.instruction_id:
        raise CodexAppServerError("instruction identity missing", "turn_start")
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


def _outcome(
    binary: str,
    state: str,
    *,
    phase: NativePhase,
    native_session_id: str | None = None,
    identity_correlated: bool = False,
) -> CodexNativeOutcome:
    """Attach the phase and the serving binary to one desktop outcome."""
    resolved = resolve_native_cli_source(binary)
    return CodexNativeOutcome(
        state,
        native_session_id,
        identity_correlated,
        phase=phase,
        binary_source=resolved.source if resolved else None,
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
                "serviceName": request.presentation or "yoke_session_relay",
            }
            if request.requested_model:
                params["model"] = request.requested_model
            identity = _identity(_thread(client.request("thread/start", params)))
            created = True
            if identity[0] != identity[1]:
                raise CodexAppServerError(
                    "thread/session identity mismatch", "identity_match"
                )
            turn_id = _start_turn(client, identity[0], request)
            client.detach_until_turn_completed(turn_id)
            return _outcome(
                self.binary,
                "accepted",
                phase="native_running",
                native_session_id=identity[0],
                identity_correlated=True,
            )
        except CodexAppServerError as failure:
            if client is not None:
                client.close()
            return _outcome(
                self.binary,
                "outcome_unknown" if created else "not_created",
                phase=failure.phase,
            )

    def wake(self, request: CodexNativeRequest) -> CodexNativeOutcome:
        if not request.target_thread_id:
            return CodexNativeOutcome("unsupported_surface")
        if not self.worker:
            return self._detached(request)
        client: _Client | None = None
        mutated = False
        try:
            client = self._client(request)
            target_thread_id = str(request.target_thread_id)
            try:
                current = _thread(
                    client.request(
                        "thread/read",
                        {"threadId": target_thread_id, "includeTurns": True},
                    )
                )
            except CodexAppServerError:
                # Resume is also the exact existence check when an unloaded
                # thread cannot be read by a fresh app-server process.
                current = None
            if current is None:
                identity = (target_thread_id, target_thread_id)
                native_status = "notLoaded"
            else:
                identity = _identity(current)
                if identity != (target_thread_id, target_thread_id):
                    raise CodexAppServerError(
                        "thread/session identity mismatch", "identity_match"
                    )
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
                    return _outcome(self.binary, "outcome_unknown", phase="turn_start")
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
                    raise CodexAppServerError(
                        "resumed identity mismatch", "identity_match"
                    )
                mutated = True
                turn_id = _start_turn(client, identity[0], request)
            else:
                client.close()
                return _outcome(self.binary, "outcome_unknown", phase="thread_open")
            client.detach_until_turn_completed(turn_id)
            return _outcome(
                self.binary,
                "accepted",
                phase="native_running",
                native_session_id=identity[0],
                identity_correlated=True,
            )
        except CodexAppServerError as failure:
            if client is not None:
                client.close()
            return _outcome(
                self.binary,
                "outcome_unknown" if mutated else "not_found",
                phase=failure.phase,
            )


__all__ = [
    "CodexAppServerError",
    "CodexAppServerTransport",
]
