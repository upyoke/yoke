"""Detached Codex app-server owner-process coverage."""

from __future__ import annotations

from io import BytesIO, StringIO
import json
import os
from pathlib import Path

from yoke_harness import session_relay_codex_app_server as app_module
from yoke_harness import session_relay_codex_app_server_process as process_module
from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV


SECRET = "one-time-worker-attestation"
INSTRUCTION = "Yoke launch launch-1: register, pull your message, act."


def _request(tmp_path: Path) -> CodexNativeRequest:
    return CodexNativeRequest(
        job_kind="launch",
        job_id="12345678-1234-4234-8234-123456789abc",
        surface="codex-desktop",
        surface_version="26.818.31338",
        checkout=tmp_path,
        requested_model=None,
        presentation=None,
        target_liveness=None,
        target_session_id=None,
        native_instruction=INSTRUCTION,
        launch_attestation=SECRET,
    )


def test_worker_request_pipe_omits_attestation(tmp_path: Path) -> None:
    request = _request(tmp_path)

    payload = process_module._request_payload(request)
    restored = process_module._request_from_payload(payload)

    assert payload["native_instruction"] == INSTRUCTION
    assert "launch_attestation" not in payload
    assert restored.native_instruction == INSTRUCTION
    assert restored.launch_attestation is None


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


class _Process:
    def __init__(self) -> None:
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.stdin = _Input(self._reply)
        self.terminated = False

    def _reply(self, body: bytes) -> None:
        request = json.loads(body)
        assert request["native_instruction"] == INSTRUCTION
        assert SECRET not in body.decode()
        response = {
            "state": "accepted",
            "native_session_id": "native-1",
            "identity_correlated": True,
            "exit_code": None,
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


def test_parent_reports_identity_while_worker_retains_turn(
    tmp_path: Path,
) -> None:
    calls = []
    process = _Process()

    def spawn(command, **options):
        calls.append((command, options))
        return process

    outcome = process_module.run_detached_operation(
        _request(tmp_path),
        executable="/opt/python",
        process_factory=spawn,
    )

    assert outcome == CodexNativeOutcome("accepted", "native-1", True)
    command, options = calls[0]
    assert command == ["/opt/python", "-m", process_module._MODULE]
    assert INSTRUCTION not in repr(command)
    assert SECRET not in repr(command)
    assert options["start_new_session"] is True
    assert options["env"]["SHELL"] == "/bin/sh"
    assert SECRET in options["env"][LAUNCH_CONTEXT_ENV]
    assert process.terminated is False


def test_worker_returns_only_bounded_outcome(monkeypatch, tmp_path: Path) -> None:
    request = _request(tmp_path)
    stdin = BytesIO(
        json.dumps(process_module._request_payload(request)).encode() + b"\n"
    )
    stdout = StringIO()
    monkeypatch.setattr(
        process_module,
        "_run_in_worker",
        lambda _request: CodexNativeOutcome("accepted", "native-1", True),
    )

    result = process_module.worker_main(stdin=stdin, stdout=stdout)

    assert result == 0
    assert json.loads(stdout.getvalue()) == {
        "state": "accepted",
        "native_session_id": "native-1",
        "identity_correlated": True,
        "exit_code": None,
    }
    assert SECRET not in stdout.getvalue()
    assert INSTRUCTION not in stdout.getvalue()


def test_app_server_turn_owner_thread_survives_worker_main(monkeypatch) -> None:
    observed = {}

    class Thread:
        def __init__(self, *, target, daemon, name) -> None:
            observed.update(target=target, daemon=daemon, name=name)

        def start(self) -> None:
            observed["started"] = True

    monkeypatch.setattr(app_module.threading, "Thread", Thread)
    client = object.__new__(app_module._Client)
    client.timeout = 1.0

    client.detach_until_turn_completed("turn-1")

    assert observed["daemon"] is False
    assert observed["started"] is True
