"""Resident hook protocol, isolation, routing, and recovery coverage."""

from __future__ import annotations

import io
import json
import multiprocessing
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock

import pytest

from yoke_cli.commands.adapters import hook_inprocess, hooks
from yoke_cli.hook_resident_client import ResidentUnavailable
from yoke_contracts.hook_evaluator_protocol import (
    HookEvaluatorRequest,
    receive_frame,
    send_frame,
)
from yoke_contracts.hook_resident_routing import is_read_only_tool_event
from yoke_contracts.hook_runner.hook_ordering import event_types
from yoke_harness.hook_resident_observations import (
    MESSAGE_PROBE_INTERVAL_SECONDS,
    ObservationQueue,
    PendingObservation,
)


def _context_evaluator(barrier: threading.Barrier):
    def evaluate(_event, _stdin, **_kwargs) -> int:
        barrier.wait(timeout=5)
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json,os;print(json.dumps([os.getcwd(),os.getenv('MARK')]))",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        print(
            json.dumps(
                {
                    "cwd": os.getcwd(),
                    "mark": os.environ.get("MARK"),
                    "pid": os.getpid(),
                    "ppid": os.getppid(),
                    "child": json.loads(child.stdout),
                }
            )
        )
        return 0

    return evaluate


def _serve_test_resident(socket_path: str, ready, mode: str) -> None:
    from yoke_harness.hook_resident import _ResidentServer

    lock_path = Path(socket_path).with_suffix(".lock")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    server = _ResidentServer(socket_path, lock_fd)
    if mode == "context":
        server.evaluate_inprocess = _context_evaluator(threading.Barrier(2))
    ready.send(server.loaded_revision)
    try:
        server.serve_forever(poll_interval=0.02)
    finally:
        server.server_close()
        server.observations.close(drain_timeout=0.1)
        server.http_opener.close()
        os.close(lock_fd)


@pytest.fixture
def resident_process():
    processes = []
    socket_paths = []

    def start(mode: str = "actual"):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        socket_path = str(
            Path(tempfile.gettempdir())
            / f"yoke-resident-test-{os.getpid()}-{len(processes)}.sock"
        )
        process = context.Process(
            target=_serve_test_resident,
            args=(socket_path, child, mode),
        )
        process.start()
        if not parent.poll(10):
            process.terminate()
            process.join(timeout=5)
            pytest.fail(
                f"resident child did not report readiness (exit={process.exitcode})"
            )
        revision = parent.recv()
        processes.append(process)
        socket_paths.append(socket_path)
        return socket_path, revision

    yield start
    for process in processes:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
    for socket_path in socket_paths:
        Path(socket_path).unlink(missing_ok=True)
        Path(socket_path).with_suffix(".lock").unlink(missing_ok=True)


def _request(
    event_name: str,
    *,
    cwd: str,
    revision: str,
    environment: dict[str, str] | None = None,
    dry_run: bool = False,
) -> HookEvaluatorRequest:
    return HookEvaluatorRequest(
        event_name=event_name,
        stdin=json.dumps(
            {
                "session_id": f"resident-{event_name.lower()}",
                "tool_name": "Read",
                "tool_input": {"file_path": "/tmp/example"},
            }
        ),
        dry_run=dry_run,
        pid=41001,
        ppid=41000,
        cwd=cwd,
        environment=environment or dict(os.environ),
        revision=revision,
    )


def _round_trip(socket_path: str, request: HookEvaluatorRequest) -> dict:
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        peer.settimeout(10)
        peer.connect(socket_path)
        send_frame(peer, request.to_mapping())
        return receive_frame(peer)
    finally:
        peer.close()


def test_resident_dry_run_matches_inprocess_for_every_hook_event(
    resident_process,
    tmp_path,
) -> None:
    socket_path, revision = resident_process()
    for event_name in event_types():
        payload = _request(
            event_name,
            cwd=str(tmp_path),
            revision=revision,
            dry_run=True,
        )
        expected_stdout = io.StringIO()
        expected_stderr = io.StringIO()
        with redirect_stdout(expected_stdout), redirect_stderr(expected_stderr):
            expected_code = hook_inprocess.evaluate_inprocess(
                event_name,
                payload.stdin,
                dry_run=True,
                cursor_invocation=False,
            )
        actual = _round_trip(socket_path, payload)
        assert actual == {
            "status": "ok",
            "stdout": expected_stdout.getvalue(),
            "stderr": expected_stderr.getvalue(),
            "exit_code": expected_code,
        }


def test_resident_isolates_concurrent_process_contexts(
    resident_process,
    tmp_path,
) -> None:
    socket_path, revision = resident_process("context")
    requests = []
    for index in (1, 2):
        cwd = tmp_path / f"caller-{index}"
        cwd.mkdir()
        environment = dict(os.environ, MARK=f"request-{index}")
        requests.append(
            _request(
                "SessionStart",
                cwd=str(cwd),
                revision=revision,
                environment=environment,
            )
        )
    results: list[dict] = []
    threads = [
        threading.Thread(
            target=lambda value=request: results.append(_round_trip(socket_path, value))
        )
        for request in requests
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(results) == 2
    contexts = [json.loads(result["stdout"]) for result in results]
    assert {item["mark"] for item in contexts} == {"request-1", "request-2"}
    assert {item["pid"] for item in contexts} == {41001}
    assert {item["ppid"] for item in contexts} == {41000}
    assert {tuple(item["child"]) for item in contexts} == {
        (str(tmp_path / "caller-1"), "request-1"),
        (str(tmp_path / "caller-2"), "request-2"),
    }


def test_revision_change_requests_resident_reexec(resident_process, tmp_path) -> None:
    socket_path, revision = resident_process()
    request = _request(
        "SessionStart",
        cwd=str(tmp_path),
        revision=f"different-{revision}",
    )
    assert _round_trip(socket_path, request) == {"status": "restart"}


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "WebSearch"])
def test_guard_free_tool_events_are_local_candidates(tool: str) -> None:
    for event_name in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        payload = json.dumps({"tool_name": tool, "session_id": "s1"})
        assert is_read_only_tool_event(event_name, payload)


@pytest.mark.parametrize("tool", ["Bash", "Write", "Edit", "Monitor"])
def test_guarded_tools_remain_relayed(tool: str) -> None:
    payload = json.dumps({"tool_name": tool, "session_id": "s1"})
    assert not is_read_only_tool_event("PreToolUse", payload)
    assert not is_read_only_tool_event("PostToolUse", payload)


def test_client_falls_back_with_named_reason(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    def unavailable(*_args, **_kwargs):
        raise ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_UNREACHABLE",
            "test socket unavailable",
            log_path=tmp_path / "resident.log",
        )

    captured = {}
    monkeypatch.setattr(
        "yoke_cli.hook_resident_client.evaluate_with_resident",
        unavailable,
    )
    monkeypatch.setattr(
        hooks,
        "_evaluate_inprocess",
        lambda *args, **kwargs: captured.update(kwargs) or 7,
    )
    assert hooks.hook_evaluate(["PreToolUse"]) == 7
    assert captured["fallback_reason"] == "YOKE_HOOK_RESIDENT_UNREACHABLE"
    assert "using canonical in-process fallback" in capsys.readouterr().err


class _BatchResponse:
    def __init__(self, accepted: int) -> None:
        self.status = 200
        self.headers = {}
        self._body = io.BytesIO(json.dumps({"accepted": accepted}).encode())

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def geturl(self) -> str:
        return "https://example.test/v1/hooks/telemetry/batch"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _pending(index: int) -> PendingObservation:
    return PendingObservation(
        observation_id=f"observation-{index}",
        endpoint="https://example.test/v1/hooks/telemetry/batch",
        authorization="Bearer test",
        observed_at="2026-09-03T20:00:00+00:00",
        hook_wait_ms=index,
        hook_request={"event_name": "PreToolUse", "stdin": "{}"},
        enqueued_at=time.monotonic(),
    )


def test_observation_flush_retains_failure_then_retries_in_order() -> None:
    calls = []

    def opener(request, timeout=None):  # noqa: ARG001
        calls.append(json.loads(request.data))
        if len(calls) == 1:
            raise OSError("offline")
        return _BatchResponse(2)

    queue = ObservationQueue(opener)
    queue.enqueue(_pending(1))
    queue.enqueue(_pending(2))
    queue._flush_once()
    assert queue.pending_count() == 2
    assert "retained 2 observation(s)" in queue.diagnostic()
    queue._flush_once()
    assert queue.pending_count() == 0
    assert [item["observation_id"] for item in calls[1]["observations"]] == [
        "observation-1",
        "observation-2",
    ]
    assert queue.close()


def test_message_probe_interval_is_bounded() -> None:
    from yoke_harness.hook_resident import _ResidentServer

    server = object.__new__(_ResidentServer)
    server.probe_lock = threading.Lock()
    server.last_message_probes = {}
    server.http_opener = Mock()
    server.http_opener.observation_batch_supported.return_value = True
    assert not server.should_evaluate_locally("session-1")
    server.mark_message_probe("session-1")
    assert server.should_evaluate_locally("session-1")
    server.last_message_probes["session-1"] -= MESSAGE_PROBE_INTERVAL_SECONDS + 1
    assert not server.should_evaluate_locally("session-1")
    server.http_opener.observation_batch_supported.return_value = False
    server.mark_message_probe("session-1")
    assert not server.should_evaluate_locally("session-1")
