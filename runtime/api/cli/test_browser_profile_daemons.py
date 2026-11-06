"""Profile daemon routing, concurrent transport scopes and bounded recovery."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest

from yoke_core.domain import browser_client as core_client
from yoke_core.domain import browser_qa
from yoke_harness import browser_client, browser_qa_daemon
from yoke_contracts.browser_daemon_profile import (
    profile_scope,
    selected_profile,
    state_file_path,
)


@pytest.mark.parametrize("client", [browser_client, core_client])
def test_stop_and_status_address_only_the_requested_profile(
    tmp_path, monkeypatch, client
):
    monkeypatch.setattr(client, "_browser_dir", lambda: tmp_path)
    a, b = str(tmp_path / "alpha"), str(tmp_path / "beta")
    for profile, pid in ((a, 101), (b, 202)):
        path = state_file_path(tmp_path, profile)
        path.parent.mkdir(parents=True)
        path.write_text(
            '{"pid":%d,"endpoint":"http://127.0.0.1:%d","token":"test",'
            '"profileDir":"%s","health":"healthy"}' % (pid, pid, profile)
        )
    requests = []
    alive = {101, 202}

    def request(path, **kwargs):
        pid = kwargs["state"].pid
        requests.append(pid)
        if path == "/api/stop":
            alive.discard(pid)
        return {"success": True, "data": {"health": "healthy"}}

    monkeypatch.setattr(
        client,
        "daemon_request",
        request,
    )
    monkeypatch.setattr(client, "daemon_running", lambda state: state.pid in alive)
    monkeypatch.setattr(
        client.os, "kill", lambda *args: (_ for _ in ()).throw(ProcessLookupError())
    )

    assert client.daemon_status(profile_dir=b)["pid"] == 202
    assert client.daemon_stop(profile_dir=a) == "stopped"
    assert requests[-1] == 101
    assert state_file_path(tmp_path, b).exists()
    with profile_scope(b):
        assert client.DaemonState.load().pid == 202


def test_profile_scopes_are_thread_local_and_restore_after_errors(tmp_path):
    barrier = Barrier(2)

    def capture(profile):
        with profile_scope(profile):
            barrier.wait(timeout=5)
            return selected_profile(), state_file_path(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as workers:
        a, b = list(workers.map(capture, [tmp_path / "alpha", tmp_path / "beta"]))
    assert a[0] != b[0]
    assert a[1] != b[1]
    assert selected_profile() == ""
    with pytest.raises(ValueError), profile_scope(tmp_path / "alpha"):
        raise ValueError("capture failed")
    assert selected_profile() == ""
    assert state_file_path(tmp_path, "") not in {a[1], b[1]}


@pytest.mark.parametrize(
    "client,ensure",
    [
        (browser_client, browser_qa_daemon.ensure_daemon_running),
        (core_client, browser_qa._ensure_daemon_running),
    ],
)
def test_transient_start_error_preserves_healthy_profile(
    tmp_path, monkeypatch, client, ensure
):
    profile = tmp_path / "alpha"
    monkeypatch.setattr(
        "yoke_cli.config.browser_profile.resolve_authorized_profile",
        lambda project, identity="default": (profile, "test profile"),
    )
    monkeypatch.setattr(client, "_browser_dir", lambda: tmp_path)
    state = client.DaemonState(pid=101, profile_dir=str(profile))
    monkeypatch.setattr(client.DaemonState, "load", lambda path=None: state)
    monkeypatch.setattr(client, "daemon_running", lambda state=None: True)
    monkeypatch.setattr(
        client,
        "daemon_health",
        Mock(return_value={"success": True, "data": {"health": "healthy"}}),
    )
    stop = Mock()
    monkeypatch.setattr(client, "daemon_stop", stop)
    start = Mock(
        side_effect=[
            RuntimeError("transient startup error"),
            {"status": "already_running"},
        ]
    )
    monkeypatch.setattr(client, "daemon_start", start)
    monkeypatch.setattr(
        "yoke_core.domain.browser_qa_daemon.time.sleep", lambda seconds: None
    )

    with profile_scope(profile):
        assert ensure(project="alpha") is None
    assert start.call_count == 2
    stop.assert_not_called()
