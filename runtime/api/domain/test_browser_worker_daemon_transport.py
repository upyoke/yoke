"""Remote worker state interoperates with the bounded daemon client."""

from __future__ import annotations

import json
from types import SimpleNamespace

from yoke_core.domain import browser_client, browser_worker
from yoke_core.domain import browser_worker_commands


class _Process:
    pid = 4242
    returncode = 0

    def poll(self):
        return None

    def terminate(self) -> None:
        return None


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, final_url: str) -> None:
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        body = b'{"status": "ok"}'
        return body if size < 0 else body[:size]

    def geturl(self) -> str:
        return self.final_url


def test_worker_state_endpoint_is_accepted_by_bounded_daemon_client(
    monkeypatch,
    tmp_path,
) -> None:
    state_holder: dict = {}
    monkeypatch.setattr(browser_worker, "_local_daemon_running", lambda _root: False)
    monkeypatch.setattr(browser_worker, "_cleanup_stale_tunnel", lambda _root: None)
    monkeypatch.setattr(browser_worker, "_tunnel_alive", lambda _root: False)
    monkeypatch.setattr(
        browser_worker,
        "lookup_remote_config",
        lambda _host, root=None: browser_worker.RemoteConfig(
            host="worker.example",
            user="test",
            key_path="",
            browser_path="/srv/browser",
            port=9222,
        ),
    )
    monkeypatch.setattr(browser_worker, "_browser_dir", lambda _root: tmp_path)
    monkeypatch.setattr(browser_worker, "_ssh_exec", lambda *_args, **_kwargs: ["ssh"])
    monkeypatch.setattr(
        browser_worker,
        "_ssh_tunnel_argv",
        lambda *_args, **_kwargs: ["ssh", "-L"],
    )
    monkeypatch.setattr(
        browser_worker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(
        browser_worker.subprocess,
        "Popen",
        lambda *_args, **_kwargs: _Process(),
    )
    monkeypatch.setattr(browser_worker, "_find_tunnel_pid", lambda *_args: 4343)
    monkeypatch.setattr(browser_worker, "_write_tunnel_pid", lambda *_args: None)
    monkeypatch.setattr(
        browser_worker,
        "_write_state",
        lambda state, _root: state_holder.update(state),
    )
    monkeypatch.setattr(browser_worker, "_emit", lambda _message: None)
    monkeypatch.setattr(browser_worker, "_now_iso", lambda: "2026-07-12T00:00:00Z")
    monkeypatch.setattr(browser_worker_commands.time, "sleep", lambda _seconds: None)

    assert browser_worker.cmd_start("worker.example", root=tmp_path) == 0
    state_path = tmp_path / "worker-state.json"
    state_path.write_text(json.dumps(state_holder), encoding="utf-8")
    state = browser_client.DaemonState.load(state_path)
    assert state is not None
    assert state.endpoint == "http://127.0.0.1:19222"

    seen = {}

    def open_daemon(request, timeout):
        seen.update(request=request, timeout=timeout)
        return _Response(request.full_url)

    monkeypatch.setattr(browser_client, "urlopen", open_daemon)

    assert browser_client.daemon_request("/api/health", state=state) == {
        "status": "ok"
    }
    assert seen["request"].full_url == "http://127.0.0.1:19222/api/health"
    assert seen["request"].get_method() == "POST"
