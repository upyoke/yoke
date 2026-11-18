"""Codex exec persists worker names independently of launch acceptance."""

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from runtime.harness.session_relay_codex_cli_process_test_support import _request
from yoke_harness import session_relay_codex_app_server_client as app
from yoke_harness import session_relay_codex_cli as cli
from yoke_harness import session_relay_codex_cli_process as owner
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_inventory import ResolvedNativeCli
from yoke_harness.session_relay_native_diagnostics import read_native_capture


@pytest.mark.parametrize("variant", ["named", "refused", "unnamed", "resume"])
def test_worker_name_is_written_only_after_the_exact_cli_thread_exits(
    monkeypatch, tmp_path: Path, variant: str
) -> None:
    thread_id = "01a038d8-96df-7802-be79-cc35851a919c"
    name = "APP-12: Worker task"
    request = replace(
        _request(tmp_path), session_name=None if variant == "unnamed" else name
    )
    if variant == "resume":
        request = replace(
            request, job_kind="wake", target_thread_id=thread_id,
            target_liveness="ended", wake_mode="waiting",
        )
    event = f'{{"type":"thread.started","thread_id":"{thread_id}"}}\n'.encode()
    capture = tmp_path / "native.capture"
    codex_store = str(tmp_path / "codex-store")
    release_native = Event()
    threads = []
    calls = []

    def start_thread(**kwargs):
        thread = Thread(**kwargs)
        threads.append(thread)
        return thread

    class Native:
        stdout = BytesIO(event)
        pid = 4242

        def wait(self, timeout):
            assert release_native.wait(10), "the test did not release the exec process"
            return 0

    class AppServer:
        def __init__(self, binary, checkout, env, timeout):
            assert release_native.is_set(), "naming tried to open an unpersisted thread"
            assert binary == "/opt/exact-codex"
            assert checkout == tmp_path
            assert env["CODEX_HOME"] == codex_store
            assert LAUNCH_CONTEXT_ENV not in env

        def request(self, method, params):
            calls.append((method, params))
            if variant == "refused":
                raise app.CodexAppServerError("thread storage refused the name")

        def close(self):
            calls.append("closed")

    monkeypatch.setenv("CODEX_HOME", codex_store)
    monkeypatch.setattr(app, "_Client", AppServer)
    monkeypatch.setattr(owner, "threading", SimpleNamespace(Thread=start_thread))
    monkeypatch.setattr(owner, "native_diagnostic_path", lambda _: capture)
    monkeypatch.setattr(
        cli, "PipeReader", lambda pipe: SimpleNamespace(read=lambda timeout: pipe.read())
    )
    transport = cli.CodexCliTransport(worker=True)
    monkeypatch.setattr(
        transport,
        "_spawn",
        lambda *_args, **_kwargs: (
            Native(),
            ResolvedNativeCli("/opt/exact-codex", "explicit"),
        ),
    )

    try:
        outcome = transport.wake(request) if variant == "resume" else transport.create(request)
        assert outcome.state == "accepted"
        assert outcome.native_session_id == thread_id
        assert calls == []
    finally:
        release_native.set()
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()

    final = read_native_capture(capture)
    assert final is not None and final.state == "exited" and final.exit_code == 0
    if variant in {"named", "refused"}:
        assert calls == [("thread/name/set", {"threadId": thread_id, "name": name}), "closed"]
    else:
        assert calls == []
    if variant == "refused":
        assert b"codex_cli_thread_name_failed" in final.stderr
        assert b"thread storage refused the name" in final.stderr
        assert b"/rename" in final.stderr
    else:
        assert final.stderr == b""
