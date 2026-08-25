"""Codex launch phase evidence and exec-stream identity correlation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_harness import session_relay_codex_app_server as app_module
from yoke_harness import session_relay_codex_app_server_client as client_module
from yoke_harness.session_relay_codex import (
    CodexNativeOutcome,
    CodexNativeRequest,
    build_codex_relay_adapter,
)
from yoke_harness.session_relay_codex_cli import CodexCliTransport
from yoke_harness.session_relay_codex_worker_protocol import (
    outcome_from_payload,
    outcome_payload,
)
from yoke_harness.session_relay_inventory import ResolvedNativeCli


THREAD_ID = "01a038d8-96df-7802-be79-cc35851a919c"
INSTRUCTION = "Yoke launch launch-1: register and check your Yoke messages."


class _FakeNative:
    """A started native whose stdout is a real pipe the selector can poll."""

    def __init__(self, payload: bytes, *, pid: int = 4242) -> None:
        read_fd, write_fd = os.pipe()
        os.write(write_fd, payload)
        os.close(write_fd)
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.stdin = None
        self.pid = pid
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.terminated = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode


def _started(thread_id: str = THREAD_ID) -> bytes:
    return (
        json.dumps({"type": "thread.started", "thread_id": thread_id}).encode() + b"\n"
    )


def _request(
    tmp_path: Path,
    *,
    job_kind: str = "launch",
    target_session_id: str | None = None,
    target_thread_id: str | None = None,
) -> CodexNativeRequest:
    return CodexNativeRequest(
        job_kind=job_kind,
        job_id="launch-1" if job_kind == "launch" else "attempt-1",
        surface="codex-cli",
        surface_version="0.149.0-alpha.4.3",
        checkout=tmp_path,
        requested_model=None,
        presentation=None,
        target_liveness="ended" if job_kind == "wake" else None,
        target_session_id=target_session_id,
        wake_mode="waiting" if job_kind == "wake" else None,
        instruction_id=f"{job_kind}:1",
        native_instruction=INSTRUCTION,
        launch_attestation="secret" if job_kind == "launch" else None,
        target_thread_id=(
            target_thread_id if target_thread_id is not None else target_session_id
        ),
    )


def _spawning(monkeypatch, native: _FakeNative, source: str = "bundled"):
    transport = CodexCliTransport(worker=True)
    monkeypatch.setattr(
        transport, "_spawn", lambda request, *, resume: (native, source)
    )
    return transport


def test_create_correlates_from_the_native_stream_and_leaves_it_running(
    monkeypatch, tmp_path: Path
) -> None:
    # The vendor exposes a thread through the app server only once its
    # rollout is persisted, which happens after the turn ends. A create that
    # confirmed identity that way killed every native it had just started.
    native = _FakeNative(_started())

    outcome = _spawning(monkeypatch, native).create(_request(tmp_path))

    assert outcome.state == "accepted"
    assert outcome.native_session_id == THREAD_ID
    assert outcome.identity_correlated is True
    assert outcome.phase == "native_running"
    assert outcome.binary_source == "bundled"
    assert outcome.pid == native.pid
    assert native.terminated is False


def test_a_native_that_announces_no_thread_names_the_identity_phase(
    monkeypatch, tmp_path: Path
) -> None:
    native = _FakeNative(b'{"type":"item.completed"}\n')

    outcome = _spawning(monkeypatch, native).create(_request(tmp_path))

    assert outcome.state == "outcome_unknown"
    assert outcome.phase == "thread_identity"
    assert outcome.pid == native.pid
    assert native.terminated is True


def test_an_unresolvable_binary_names_the_resolve_phase(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_codex_cli.resolve_native_cli_source",
        lambda _binary: None,
    )

    outcome = CodexCliTransport(worker=True).create(_request(tmp_path))

    assert outcome.state == "not_created"
    assert outcome.phase == "binary_resolve"
    assert outcome.binary_source is None


def test_a_resume_onto_another_thread_names_the_identity_match_phase(
    monkeypatch, tmp_path: Path
) -> None:
    native = _FakeNative(_started("01a038d8-0000-0000-0000-000000000000"))
    transport = _spawning(monkeypatch, native)

    outcome = transport.wake(
        _request(tmp_path, job_kind="wake", target_session_id=THREAD_ID)
    )

    assert outcome.state == "outcome_unknown"
    assert outcome.identity_correlated is False
    assert outcome.phase == "identity_match"
    assert native.terminated is True


def test_phase_evidence_survives_the_worker_and_report_boundaries(
    tmp_path: Path,
) -> None:
    outcome = CodexNativeOutcome(
        "outcome_unknown",
        phase="thread_identity",
        binary_source="path",
        pid=4242,
    )
    assert outcome_from_payload(outcome_payload(outcome)) == outcome

    adapter = build_codex_relay_adapter(
        cli_transport=type("Port", (), {"create": lambda _self, _r: outcome})(),
        desktop_transport=None,
        version_gate=lambda *_args: True,
    )
    result = adapter(
        type("Context", (), {**_request(tmp_path).__dict__, "lease_id": "lease-1"})()
    )
    durable = redacted_evidence_document(result.evidence)

    assert durable["native_launch_phase"] == "thread_identity"
    assert durable["native_binary_source"] == "path"
    assert durable["native_launch_pid"] == 4242


def test_transport_exception_records_spawn_phase_and_private_diagnostic(
    tmp_path: Path,
) -> None:
    class Exploding:
        def create(self, _request):
            raise OSError("spawn refused")

    adapter = build_codex_relay_adapter(
        cli_transport=Exploding(),
        desktop_transport=None,
        version_gate=lambda *_args: True,
    )

    result = adapter(
        type("Context", (), {**_request(tmp_path).__dict__, "lease_id": "lease-1"})()
    )

    assert result.result_code == "outcome_unknown"
    assert result.evidence["result_code"] == "transport_exception"
    assert result.evidence["native_launch_phase"] == "spawn"
    assert result.private_diagnostic is not None
    assert result.private_diagnostic.error_step == "launch"
    assert result.private_diagnostic.stderr == b"spawn refused"


def test_an_app_server_failure_names_the_method_it_failed(monkeypatch) -> None:
    client = object.__new__(client_module._Client)
    client.timeout = 1.0
    client.next_id = 1
    monkeypatch.setattr(client_module._Client, "_send", lambda _self, _payload: None)
    monkeypatch.setattr(
        client_module._Client,
        "_receive",
        lambda _self, _deadline: {"id": 1, "error": {"code": -1, "message": "no"}},
    )

    with pytest.raises(client_module.CodexAppServerError) as failure:
        client.request("thread/start", {})

    assert failure.value.phase == "thread_open"


def test_an_app_server_exchange_stops_at_its_own_deadline(monkeypatch) -> None:
    # A peer that keeps sending unrelated notifications never blocks on a
    # read, so bounding only each read leaves the caller here forever.
    client = object.__new__(client_module._Client)
    client.timeout = 0.05
    client.next_id = 1
    monkeypatch.setattr(client_module._Client, "_send", lambda _self, _payload: None)
    monkeypatch.setattr(
        client_module._Client,
        "_receive",
        lambda _self, _deadline: {"method": "thread/event", "params": {}},
    )

    with pytest.raises(client_module.CodexAppServerError) as failure:
        client.request("turn/start", {})

    assert failure.value.phase == "turn_start"


def test_a_desktop_create_records_its_phase_and_serving_binary(
    monkeypatch, tmp_path: Path
) -> None:
    class Refusing:
        def request(self, method: str, _params: dict) -> dict:
            raise client_module.CodexAppServerError(f"{method} failed", "thread_open")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        app_module.CodexAppServerTransport, "_client", lambda *_args: Refusing()
    )
    monkeypatch.setattr(
        app_module,
        "resolve_native_cli_source",
        lambda _binary: ResolvedNativeCli("/opt/codex", "path"),
    )

    outcome = app_module.CodexAppServerTransport(worker=True).create(_request(tmp_path))

    assert outcome.state == "not_created"
    assert outcome.phase == "thread_open"
    assert outcome.binary_source == "path"
