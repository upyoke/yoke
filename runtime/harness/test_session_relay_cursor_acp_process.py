"""Cursor ACP owner lifetime, policy, and terminal acknowledgment coverage."""

from __future__ import annotations

from io import BytesIO, StringIO
import json
import os
from pathlib import Path

from yoke_harness import session_relay_cursor_acp as acp_module
from yoke_harness import session_relay_cursor_acp_process as process_module
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_cursor import CursorCreateRequest, CursorNativeResult
from yoke_harness.session_relay_cursor_acp_terminal import (
    CursorAcpTerminalRegistry,
    respond_to_agent_request,
)


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
SECRET = "cursor-acp-owner-attestation"
INSTRUCTION = f"Yoke launch `{LAUNCH_ID}`: register, pull your message, act."


def _request(tmp_path: Path) -> CursorCreateRequest:
    return CursorCreateRequest(
        checkout=tmp_path,
        launch_id=LAUNCH_ID,
        surface_version="2026.08.11-e8db854",
        native_instruction=INSTRUCTION,
        launch_attestation=SECRET,
        requested_model="composer-2",
    )


class _Input:
    def __init__(self, on_close) -> None:
        self.body = bytearray()
        self.on_close = on_close

    def write(self, value: bytes) -> int:
        self.body.extend(value)
        return len(value)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.on_close(bytes(self.body))


class _OwnerProcess:
    def __init__(self) -> None:
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.stdin = _Input(self._reply)
        self.terminated = False

    def _reply(self, body: bytes) -> None:
        payload = json.loads(body)
        assert payload["native_instruction"] == INSTRUCTION
        assert SECRET not in body.decode()
        response = {
            "result_code": "native_created",
            "native_session_id": SESSION_ID,
            "exit_code": None,
            "duration_ms": 10,
        }
        os.write(self.write_fd, json.dumps(response).encode() + b"\n")
        os.close(self.write_fd)

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


def test_detached_acp_owner_retains_pipes_after_parent_result(tmp_path: Path) -> None:
    calls = []
    process = _OwnerProcess()

    outcome = process_module.run_detached_operation(
        _request(tmp_path),
        executable="/opt/python",
        process_factory=lambda command, **options: (
            calls.append((command, options)) or process
        ),
    )

    assert outcome == CursorNativeResult("native_created", SESSION_ID, None, 10)
    command, options = calls[0]
    assert command == ["/opt/python", "-m", process_module._MODULE]
    assert options["start_new_session"] is True
    assert SECRET in options["env"][LAUNCH_CONTEXT_ENV]
    assert SECRET not in repr(command)
    assert INSTRUCTION not in repr(command)
    assert process.terminated is False


def test_acp_worker_rehydrates_secret_and_returns_metadata_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    observed = []
    monkeypatch.setattr(
        process_module,
        "_run_in_worker",
        lambda value: (
            observed.append(value)
            or CursorNativeResult("native_created", SESSION_ID, duration_ms=2)
        ),
    )
    stdout = StringIO()

    assert (
        process_module.worker_main(
            stdin=BytesIO(
                json.dumps(process_module._request_payload(request)).encode()
            ),
            stdout=stdout,
            environ={
                LAUNCH_CONTEXT_ENV: json.dumps(
                    {"launch_id": LAUNCH_ID, "attestation": SECRET}
                )
            },
        )
        == 0
    )

    assert observed[0].launch_attestation == SECRET
    assert SECRET not in repr(observed[0])
    assert json.loads(stdout.getvalue())["native_session_id"] == SESSION_ID
    assert SECRET not in stdout.getvalue()
    assert INSTRUCTION not in stdout.getvalue()


def test_acp_default_delegates_to_detached_owner(monkeypatch, tmp_path: Path) -> None:
    request = _request(tmp_path)
    expected = CursorNativeResult("native_created", SESSION_ID)
    calls = []
    monkeypatch.setattr(
        acp_module.CursorAcpTransport,
        "_detached",
        staticmethod(lambda value: calls.append(value) or expected),
    )

    assert acp_module.CursorAcpTransport().new_session(request) == expected
    assert calls == [request]


def test_acp_advertises_terminal_without_read_write_proxy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    class Client:
        def __init__(self, *_args) -> None:
            pass

        def request(self, method, params):
            calls.append((method, params))
            return {}

        def close(self) -> None:
            pass

    monkeypatch.setattr(acp_module, "_Client", Client)

    acp_module.CursorAcpTransport(worker=True)._client(tmp_path, _request(tmp_path))

    initialize = calls[0][1]
    assert initialize["clientCapabilities"] == {
        "fs": {"readTextFile": False, "writeTextFile": False},
        "terminal": True,
    }


class _CommandProcess:
    def __init__(self) -> None:
        self.stdout = BytesIO(b'{"acknowledged":true}\n')
        self.returncode = 0
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


def test_acp_terminal_executes_explicit_ack_without_shell(tmp_path: Path) -> None:
    calls = []
    registry = CursorAcpTerminalRegistry(
        tmp_path,
        environ={"PATH": "/opt/bin"},
        process_factory=lambda command, **options: (
            calls.append((command, options)) or _CommandProcess()
        ),
    )
    response = respond_to_agent_request(
        registry,
        {
            "id": 7,
            "method": "terminal/create",
            "params": {
                "sessionId": SESSION_ID,
                "command": "/opt/yoke",
                "args": ["sessions", "messages", "ack", "message-1"],
                "cwd": str(tmp_path),
            },
        },
    )
    terminal_id = response["result"]["terminalId"]
    wait = respond_to_agent_request(
        registry,
        {
            "id": 8,
            "method": "terminal/wait_for_exit",
            "params": {"sessionId": SESSION_ID, "terminalId": terminal_id},
        },
    )

    assert calls[0][0] == [
        "/opt/yoke",
        "sessions",
        "messages",
        "ack",
        "message-1",
    ]
    assert "shell" not in calls[0][1]
    assert wait["result"] == {"exitCode": 0, "signal": None}


def test_acp_permission_uses_vendor_allow_once_option(tmp_path: Path) -> None:
    registry = CursorAcpTerminalRegistry(tmp_path, environ={})
    response = respond_to_agent_request(
        registry,
        {
            "id": 9,
            "method": "session/request_permission",
            "params": {
                "options": [
                    {"optionId": "no", "kind": "reject_once"},
                    {"optionId": "yes", "kind": "allow_once"},
                ]
            },
        },
    )

    assert response["result"] == {"outcome": {"outcome": "selected", "optionId": "yes"}}


def test_acp_prompt_owner_thread_is_non_daemon(monkeypatch) -> None:
    observed = {}

    class Thread:
        def __init__(self, *, target, daemon, name) -> None:
            observed.update(target=target, daemon=daemon, name=name)

        def start(self) -> None:
            observed["started"] = True

    client = object.__new__(acp_module._Client)
    client.timeout = 1.0
    monkeypatch.setattr(client, "_request_id", lambda *_args: 1)
    monkeypatch.setattr(acp_module.threading, "Thread", Thread)

    client.start_prompt(SESSION_ID, INSTRUCTION)

    assert observed["daemon"] is False
    assert observed["started"] is True
