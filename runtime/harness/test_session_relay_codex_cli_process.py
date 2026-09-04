"""Codex CLI owner-process lifetime and inherited-policy coverage."""

from __future__ import annotations

from io import BytesIO, StringIO
import json
import os
from pathlib import Path

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_harness import session_relay_codex_app_server as app_module
from yoke_harness import session_relay_codex_cli as cli_module
from yoke_harness import session_relay_codex_cli_process as process_module
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest
from yoke_harness.session_relay_codex_invocation import codex_base_command
from yoke_harness.session_relay_inventory import ResolvedNativeCli
from yoke_harness.session_relay_codex_worker_protocol import request_payload


SECRET = "codex-cli-owner-attestation"
INSTRUCTION = native_launch_bootstrap("launch-1")


def _request(tmp_path: Path, *, surface: str = "codex-cli") -> CodexNativeRequest:
    return CodexNativeRequest(
        job_kind="launch",
        job_id="12345678-1234-4234-8234-123456789abc",
        surface=surface,
        surface_version="0.148.0-alpha.15",
        checkout=tmp_path,
        requested_model="gpt-5.6",
        presentation="focused",
        target_liveness=None,
        target_session_id=None,
        wake_mode=None,
        instruction_id="launch:12345678-1234-4234-8234-123456789abc",
        native_instruction=INSTRUCTION,
        launch_attestation=SECRET,
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


class _Process:
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


def test_detached_cli_owner_retains_process_after_parent_result(tmp_path: Path) -> None:
    calls = []
    process = _Process()

    outcome = process_module.run_detached_operation(
        _request(tmp_path),
        executable="/opt/python",
        process_factory=lambda command, **options: (
            calls.append((command, options)) or process
        ),
    )

    assert outcome == CodexNativeOutcome("accepted", "native-1", True)
    command, options = calls[0]
    assert command == ["/opt/python", "-m", process_module._MODULE]
    assert options["start_new_session"] is True
    assert SECRET in options["env"][LAUNCH_CONTEXT_ENV]
    assert SECRET not in repr(command)
    assert INSTRUCTION not in repr(command)
    assert process.terminated is False


def test_cli_worker_rehydrates_secret_and_returns_bounded_outcome(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    observed = []
    monkeypatch.setattr(
        process_module,
        "_run_in_worker",
        lambda value: (
            observed.append(value) or CodexNativeOutcome("accepted", "native-1", True)
        ),
    )
    stdout = StringIO()

    assert (
        process_module.worker_main(
            stdin=BytesIO(json.dumps(request_payload(request)).encode()),
            stdout=stdout,
            environ={
                LAUNCH_CONTEXT_ENV: json.dumps(
                    {"launch_id": request.job_id, "attestation": SECRET}
                )
            },
        )
        == 0
    )

    assert observed[0].launch_attestation == SECRET
    assert SECRET not in repr(observed[0])
    assert json.loads(stdout.getvalue())["native_session_id"] == "native-1"
    assert SECRET not in stdout.getvalue()
    assert INSTRUCTION not in stdout.getvalue()


def test_cli_default_delegates_to_detached_owner(monkeypatch, tmp_path: Path) -> None:
    request = _request(tmp_path)
    calls = []
    expected = CodexNativeOutcome("accepted", "native-1", True)
    monkeypatch.setattr(
        cli_module.CodexCliTransport,
        "_detached",
        staticmethod(lambda value: calls.append(value) or expected),
    )

    assert cli_module.CodexCliTransport().create(request) == expected
    assert calls == [request]


def test_cli_instruction_crosses_stdin_not_process_arguments(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []
    bodies = []
    child = type(
        "Child",
        (),
        {
            "stdin": _Input(bodies.append),
            "stdout": BytesIO(),
            # The transport drains stderr from the spawn onward, so a native
            # that refuses before announcing a thread still leaves its reason.
            "stderr": BytesIO(),
        },
    )()
    monkeypatch.setattr(
        cli_module.subprocess,
        "Popen",
        lambda command, **options: calls.append((command, options)) or child,
    )
    monkeypatch.setattr(
        cli_module,
        "resolve_native_cli_source",
        lambda binary: ResolvedNativeCli(binary, "explicit"),
    )

    process, binary_source = cli_module.CodexCliTransport(
        binary="/opt/codex",
        worker=True,
    )._spawn(_request(tmp_path), resume=False, streams=cli_module.BoundedStreams())

    assert process is child
    assert binary_source == "explicit"
    command, options = calls[0]
    assert command[-1] == "-"
    assert INSTRUCTION not in repr(command)
    assert SECRET not in repr(command)
    assert options["stdin"] is cli_module.subprocess.PIPE
    assert bodies == [INSTRUCTION.encode()]


def test_codex_launches_run_unattended_on_both_transports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    command = codex_base_command("/opt/codex", request)
    assert command == [
        "/opt/codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "--model",
        "gpt-5.6",
    ]

    class Client:
        def __init__(self) -> None:
            self.calls = []
            self.detached = None

        def request(self, method, params):
            self.calls.append((method, params))
            if method == "thread/start":
                return {"thread": {"id": "native-1", "sessionId": "native-1"}}
            return {"turn": {"id": "turn-1"}}

        def detach_until_turn_completed(self, turn_id):
            self.detached = turn_id

        def close(self):
            pass

    client = Client()
    transport = app_module.CodexAppServerTransport(worker=True)
    monkeypatch.setattr(transport, "_client", lambda _request: client)

    outcome = transport.create(_request(tmp_path, surface="codex-desktop"))

    assert outcome.state == "accepted"
    params = next(value for method, value in client.calls if method == "thread/start")
    assert params["sandbox"] == "danger-full-access"
    assert params["approvalPolicy"] == "never"
    turn = next(value for method, value in client.calls if method == "turn/start")
    assert turn["approvalPolicy"] == "never"
    assert turn["sandboxPolicy"] == {"type": "dangerFullAccess"}


def test_cli_drain_thread_is_non_daemon(monkeypatch) -> None:
    observed = {}

    class Thread:
        def __init__(self, *, target, daemon, name) -> None:
            observed.update(target=target, daemon=daemon, name=name)

        def start(self) -> None:
            observed["started"] = True

    class Process:
        stdout = None

        def wait(self):
            return 0

    monkeypatch.setattr(cli_module.threading, "Thread", Thread)
    cli_module._retain_and_reap(
        Process(),
        cli_module.BoundedStreams(),
        "11111111-1111-4111-8111-111111111111",
    )

    assert observed["daemon"] is False
    assert observed["started"] is True
