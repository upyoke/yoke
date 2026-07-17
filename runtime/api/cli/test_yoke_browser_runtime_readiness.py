"""Browser runtime readiness and endpoint-diagnostic contracts."""

from __future__ import annotations

import subprocess
import urllib.error
from unittest.mock import patch

import pytest

from yoke_harness import browser_client
from yoke_harness.browser_qa_daemon import ensure_daemon_running


def _prepare_daemon_launch(tmp_path, monkeypatch):
    browser = tmp_path / "browser-runtime"
    browser.joinpath("src").mkdir(parents=True)
    browser.joinpath("src", "daemon.js").write_text("", encoding="utf-8")
    browser.joinpath("node_modules", "playwright").mkdir(parents=True)
    state = browser_client.DaemonState(
        pid=321,
        token="secret-token",
        endpoint="http://127.0.0.1:9222",
        health="healthy",
    )
    loads = iter([None, state, state, state])

    class FakeProcess:
        pid = 321

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["node"], timeout)

        def kill(self):
            raise AssertionError("healthy daemon must not be killed")

    def fake_run(command, **_kwargs):
        if command[:2] == ["which", "node"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["node", "-e"]:
            return subprocess.CompletedProcess(command, 0, "ok", "")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(browser_client, "_browser_dir", lambda: browser)
    monkeypatch.setattr(
        browser_client,
        "_state_file_path",
        lambda: browser / ".daemon-state.json",
    )
    monkeypatch.setattr(
        browser_client.DaemonState,
        "load",
        staticmethod(lambda path=None: next(loads)),
    )
    monkeypatch.setattr(browser_client.subprocess, "run", fake_run)
    monkeypatch.setattr(
        browser_client.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(),
    )
    monkeypatch.setattr(browser_client.time, "sleep", lambda _seconds: None)
    return state


def test_daemon_start_waits_for_authenticated_health_endpoint(
    tmp_path,
    monkeypatch,
) -> None:
    state = _prepare_daemon_launch(tmp_path, monkeypatch)
    attempts = iter(
        [
            RuntimeError("endpoint refused connection"),
            RuntimeError("endpoint refused connection"),
            {"success": True, "data": {"health": "healthy"}},
        ]
    )
    calls: list[tuple[str, int, browser_client.DaemonState]] = []

    def fake_request(path, body=None, timeout=30, state=None):
        calls.append((path, timeout, state))
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(browser_client, "daemon_request", fake_request)

    assert browser_client.daemon_start() == {
        "status": "started",
        "endpoint": state.endpoint,
        "pid": state.pid,
    }
    assert calls == [
        ("/api/health", 1, state),
        ("/api/health", 1, state),
        ("/api/health", 1, state),
    ]


def test_daemon_request_failure_names_endpoint_and_pid(monkeypatch) -> None:
    state = browser_client.DaemonState(
        pid=654,
        token="secret-token",
        endpoint="http://127.0.0.1:9333",
        health="healthy",
    )
    monkeypatch.setattr(
        browser_client.DaemonState,
        "load",
        staticmethod(lambda path=None: state),
    )

    def refuse_connection(*_args, **_kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(browser_client, "urlopen", refuse_connection)

    with pytest.raises(RuntimeError) as exc_info:
        browser_client.daemon_request("/api/health")

    message = str(exc_info.value)
    assert "endpoint=http://127.0.0.1:9333/api/health" in message
    assert "pid=654" in message
    assert "secret-token" not in message


def test_daemon_status_reports_live_pid_with_unreachable_endpoint(
    monkeypatch,
) -> None:
    state = browser_client.DaemonState(
        pid=700,
        token="token",
        endpoint="http://127.0.0.1:9666",
        health="healthy",
    )
    monkeypatch.setattr(
        browser_client.DaemonState,
        "load",
        staticmethod(lambda path=None: state),
    )
    monkeypatch.setattr(browser_client, "daemon_running", lambda _state: True)

    def unreachable_health(**_kwargs):
        raise RuntimeError("health endpoint unreachable")

    monkeypatch.setattr(browser_client, "daemon_health", unreachable_health)

    status = browser_client.daemon_status()

    assert status["status"] == "unready"
    assert status["health"] == "unreachable"
    assert status["endpoint"] == state.endpoint
    assert status["pid"] == state.pid
    assert "health endpoint unreachable" in status["error"]


def test_itemless_capture_recovers_pid_without_healthy_endpoint() -> None:
    state = browser_client.DaemonState(
        pid=777,
        token="token",
        endpoint="http://127.0.0.1:9444",
        health="healthy",
    )
    with (
        patch(
            "yoke_harness.browser_client.DaemonState.load",
            return_value=state,
        ),
        patch(
            "yoke_harness.browser_client.daemon_running",
            return_value=True,
        ),
        patch(
            "yoke_harness.browser_client.daemon_health",
            side_effect=RuntimeError("health endpoint unreachable"),
        ) as health,
        patch(
            "yoke_harness.browser_client.daemon_stop",
            return_value="stopped",
        ) as stop,
        patch(
            "yoke_harness.browser_client.daemon_start",
            return_value={"status": "started"},
        ) as start,
    ):
        assert ensure_daemon_running() is None

    health.assert_called_once_with(state=state, timeout=1)
    stop.assert_called_once_with()
    start.assert_called_once_with()


def test_itemless_capture_reuses_daemon_only_after_health_check() -> None:
    state = browser_client.DaemonState(
        pid=888,
        token="token",
        endpoint="http://127.0.0.1:9555",
        health="healthy",
    )
    with (
        patch(
            "yoke_harness.browser_client.DaemonState.load",
            return_value=state,
        ),
        patch(
            "yoke_harness.browser_client.daemon_running",
            return_value=True,
        ),
        patch(
            "yoke_harness.browser_client.daemon_health",
            return_value={"success": True, "data": {"health": "healthy"}},
        ) as health,
        patch(
            "yoke_harness.browser_client.daemon_start",
        ) as start,
    ):
        assert ensure_daemon_running() is None

    health.assert_called_once_with(state=state, timeout=1)
    start.assert_not_called()
