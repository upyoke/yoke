"""Tests for browser_client.py — daemon client and lifecycle management.

Covers: state file loading, daemon status detection, HTTP client, viewport parsing,
step execution, snapshot primitives, and CLI entry point.

These tests mock the filesystem and HTTP layer — no real daemon or node process needed.
"""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from yoke_core.domain.browser_client import (
    DaemonState,
    daemon_running,
    daemon_status,
    execute_step,
    snapshot_accessibility,
    snapshot_screenshot,
    snapshot_diff,
    daemon_request,
    _parse_viewport,
    main,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state_file(tmp_path):
    """Create a daemon state file for testing."""
    sf = tmp_path / ".daemon-state.json"
    data = {
        "pid": os.getpid(),  # Use current PID so kill -0 succeeds
        "token": "test-token-abc",
        "endpoint": "http://127.0.0.1:9222",
        "browserType": "chromium",
        "startedAt": "2026-04-09T00:00:00Z",
        "health": "healthy",
        "port": 9222,
    }
    sf.write_text(json.dumps(data))
    return sf


@pytest.fixture
def dead_state_file(tmp_path):
    """State file with a PID that doesn't exist."""
    sf = tmp_path / ".daemon-state.json"
    data = {
        "pid": 999999999,
        "token": "dead-token",
        "endpoint": "http://127.0.0.1:9222",
        "browserType": "chromium",
        "startedAt": "2026-04-09T00:00:00Z",
        "health": "healthy",
        "port": 9222,
    }
    sf.write_text(json.dumps(data))
    return sf


# ---------------------------------------------------------------------------
# DaemonState
# ---------------------------------------------------------------------------

class TestDaemonState:
    def test_load_valid(self, state_file):
        st = DaemonState.load(state_file)
        assert st is not None
        assert st.pid == os.getpid()
        assert st.token == "test-token-abc"
        assert st.endpoint == "http://127.0.0.1:9222"
        assert st.health == "healthy"
        assert st.port == 9222

    def test_load_missing_file(self, tmp_path):
        st = DaemonState.load(tmp_path / "nonexistent.json")
        assert st is None

    def test_load_invalid_json(self, tmp_path):
        sf = tmp_path / "bad.json"
        sf.write_text("not json")
        st = DaemonState.load(sf)
        assert st is None

    def test_load_empty_file(self, tmp_path):
        sf = tmp_path / "empty.json"
        sf.write_text("")
        st = DaemonState.load(sf)
        assert st is None


# ---------------------------------------------------------------------------
# daemon_running
# ---------------------------------------------------------------------------

class TestDaemonRunning:
    def test_running_with_live_pid(self, state_file):
        st = DaemonState.load(state_file)
        assert daemon_running(st) is True

    def test_not_running_with_dead_pid(self, dead_state_file):
        st = DaemonState.load(dead_state_file)
        assert daemon_running(st) is False

    def test_not_running_no_state(self, tmp_path):
        with mock.patch("yoke_core.domain.browser_client._state_file_path", return_value=tmp_path / "nope.json"):
            assert daemon_running(None) is False

    def test_not_running_zero_pid(self):
        st = DaemonState(pid=0, token="t", endpoint="http://x")
        assert daemon_running(st) is False


# ---------------------------------------------------------------------------
# daemon_status
# ---------------------------------------------------------------------------

class TestDaemonStatus:
    def test_running(self, state_file):
        with mock.patch("yoke_core.domain.browser_client._state_file_path", return_value=state_file):
            result = daemon_status()
            assert result["status"] == "running"
            assert result["health"] == "healthy"

    def test_crashed(self, dead_state_file):
        with mock.patch("yoke_core.domain.browser_client._state_file_path", return_value=dead_state_file):
            result = daemon_status()
            assert result["status"] == "crashed"

    def test_not_running(self, tmp_path):
        with mock.patch("yoke_core.domain.browser_client._state_file_path", return_value=tmp_path / "nope.json"):
            result = daemon_status()
            assert result["status"] == "not_running"


# ---------------------------------------------------------------------------
# daemon_request
# ---------------------------------------------------------------------------

class TestDaemonRequest:
    def test_raises_without_state(self, tmp_path):
        with mock.patch("yoke_core.domain.browser_client._state_file_path", return_value=tmp_path / "nope.json"):
            with pytest.raises(RuntimeError, match="daemon not running"):
                daemon_request("/api/health", state=None)

    def test_raises_with_empty_endpoint(self):
        st = DaemonState(pid=1, token="t", endpoint="")
        with pytest.raises(RuntimeError, match="invalid state"):
            daemon_request("/api/health", state=st)

    def test_success(self, state_file):
        st = DaemonState.load(state_file)
        response_json = json.dumps({"status": "ok"}).encode()

        with mock.patch("yoke_core.domain.browser_client.urlopen") as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = response_json
            mock_resp.read1 = None
            mock_resp.status = 200
            mock_resp.headers = {}
            mock_resp.geturl.return_value = "http://127.0.0.1:9222/api/health"
            mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = mock.MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = daemon_request("/api/health", state=st)
            assert result == {"status": "ok"}


# ---------------------------------------------------------------------------
# Viewport parsing
# ---------------------------------------------------------------------------

class TestParseViewport:
    def test_standard(self):
        assert _parse_viewport("1280x720") == (1280, 720)

    def test_uppercase(self):
        assert _parse_viewport("1920X1080") == (1920, 1080)

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid viewport"):
            _parse_viewport("invalid")


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------

class TestExecuteStep:
    def test_calls_daemon(self):
        with mock.patch("yoke_core.domain.browser_client.daemon_request") as mock_req:
            mock_req.return_value = {"success": True, "screenshot": "/path/to/img.png"}
            result = execute_step({"action": "navigate", "route": "/"}, "http://localhost:3000")
            assert result["success"] is True
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            assert call_args[0][0] == "/api/exec/step"
            body = call_args[0][1]
            assert body["baseUrl"] == "http://localhost:3000"

    def test_with_output_dir(self):
        with mock.patch("yoke_core.domain.browser_client.daemon_request") as mock_req:
            mock_req.return_value = {}
            execute_step({"action": "click"}, "http://x", output_dir="/tmp/out")
            body = mock_req.call_args[0][1]
            assert body["outputDir"] == "/tmp/out"


# ---------------------------------------------------------------------------
# Snapshot primitives
# ---------------------------------------------------------------------------

class TestSnapshots:
    def test_accessibility(self):
        with mock.patch("yoke_core.domain.browser_client.daemon_request") as mock_req:
            mock_req.return_value = {"tree": []}
            result = snapshot_accessibility("http://localhost:3000")
            assert result == {"tree": []}
            mock_req.assert_called_once_with("/api/snapshot/accessibility", {"url": "http://localhost:3000"})

    def test_screenshot_basic(self):
        with mock.patch("yoke_core.domain.browser_client.daemon_request") as mock_req:
            mock_req.return_value = {"screenshot": "/path.png"}
            snapshot_screenshot("http://x")
            body = mock_req.call_args[0][1]
            assert body["url"] == "http://x"
            assert body["annotate"] is False

    def test_screenshot_with_viewport(self):
        with mock.patch("yoke_core.domain.browser_client.daemon_request") as mock_req:
            mock_req.return_value = {}
            snapshot_screenshot("http://x", viewport="1280x720")
            body = mock_req.call_args[0][1]
            assert body["viewport"] == {"width": 1280, "height": 720}

    def test_diff(self):
        with mock.patch("yoke_core.domain.browser_client.daemon_request") as mock_req:
            mock_req.return_value = {"diffPercent": 0.5}
            snapshot_diff("http://x", baseline="/b.png", viewport="800x600")
            body = mock_req.call_args[0][1]
            assert body["baselinePath"] == "/b.png"
            assert body["viewport"] == {"width": 800, "height": 600}

    def test_diff_with_threshold(self):
        with mock.patch("yoke_core.domain.browser_client.daemon_request") as mock_req:
            mock_req.return_value = {}
            snapshot_diff("http://x", baseline="/b.png", viewport="800x600", threshold=0.1)
            body = mock_req.call_args[0][1]
            assert body["threshold"] == 0.1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_daemon_status(self, state_file):
        with mock.patch("yoke_core.domain.browser_client._state_file_path", return_value=state_file):
            with mock.patch("sys.argv", ["browser_client", "daemon", "status"]):
                rc = main()
                assert rc == 0

    def test_no_args(self):
        with mock.patch("sys.argv", ["browser_client"]):
            rc = main()
            assert rc == 3
