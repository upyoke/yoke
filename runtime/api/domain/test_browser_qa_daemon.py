"""Browser QA — daemon retry and diagnostics suites."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from yoke_core.domain import browser_qa


# ---------------------------------------------------------------------------
# Daemon auto-retry and diagnostics
# ---------------------------------------------------------------------------

class TestDaemonRetry:
    """_ensure_daemon_running performs bounded auto-recovery."""

    def test_retry_succeeds_on_second_attempt(self) -> None:
        """AC-5: If a retry succeeds, execution continues normally."""
        call_count = 0

        def _fake_start(**_kw: Any) -> Dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("port in use")
            return {"status": "started"}

        with mock.patch("yoke_core.domain.browser_qa.time.sleep"), \
             mock.patch("yoke_core.domain.browser_client.daemon_running", return_value=False), \
             mock.patch("yoke_core.domain.browser_client.daemon_start", side_effect=_fake_start), \
             mock.patch("yoke_core.domain.browser_client.daemon_stop", return_value="stopped"):
            result = browser_qa._ensure_daemon_running()

        assert result is None  # success
        assert call_count == 2  # first failed, second succeeded

    def test_retry_exhausted_returns_error_with_diagnostics(self) -> None:
        """AC-2/AC-4: After max retries, returns error with diagnostics."""
        with mock.patch("yoke_core.domain.browser_client.daemon_running", return_value=False), \
             mock.patch("yoke_core.domain.browser_client.daemon_start", side_effect=RuntimeError("persistent failure")), \
             mock.patch("yoke_core.domain.browser_client.daemon_stop", return_value="stopped"), \
             mock.patch.object(browser_qa, "_collect_daemon_diagnostics", return_value={
                 "stderr_tail": "Error: EADDRINUSE",
                 "daemon_status": {"status": "crashed"},
                 "daemon_health": {"status": "degraded"},
             }), \
             mock.patch.object(browser_qa, "_emit_daemon_startup_failed_event") as mock_emit, \
             mock.patch("yoke_core.domain.browser_qa.time.sleep"):
            result = browser_qa._ensure_daemon_running()

        assert result is not None
        assert "3 attempts" in result
        assert "persistent failure" in result
        assert "EADDRINUSE" in result
        assert "degraded" in result
        # Event should have been emitted
        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        assert call_kwargs[1]["attempt_count"] == 3
        assert "persistent failure" in call_kwargs[1]["last_error"]

    def test_retry_logs_each_attempt(self) -> None:
        """AC-3: Each retry attempt and outcome are logged."""
        logged_messages: List[str] = []

        def _capture_log(msg: str) -> None:
            logged_messages.append(msg)

        call_count = 0

        def _fake_start(**_kw: Any) -> Dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError(f"failure #{call_count}")
            return {"status": "started"}

        with mock.patch.object(browser_qa, "_log", side_effect=_capture_log), \
             mock.patch("yoke_core.domain.browser_client.daemon_running", return_value=False), \
             mock.patch("yoke_core.domain.browser_client.daemon_start", side_effect=_fake_start), \
             mock.patch("yoke_core.domain.browser_client.daemon_stop", return_value="stopped"), \
             mock.patch("yoke_core.domain.browser_qa.time.sleep"):
            result = browser_qa._ensure_daemon_running()

        assert result is None  # third attempt succeeds
        # Check that retry attempts were logged
        retry_msgs = [m for m in logged_messages if "Retry" in m or "attempt" in m]
        assert len(retry_msgs) >= 2  # at least the two retry log lines

    def test_daemon_already_running_skips_retry(self) -> None:
        """Baseline: if daemon is already running, no retry logic executes."""
        with mock.patch("yoke_core.domain.browser_client.daemon_running", return_value=True):
            result = browser_qa._ensure_daemon_running()
        assert result is None

    def test_first_attempt_success_skips_retry(self) -> None:
        """Baseline: if first start succeeds, no retry logic executes."""
        with mock.patch("yoke_core.domain.browser_client.daemon_running", return_value=False), \
             mock.patch("yoke_core.domain.browser_client.daemon_start", return_value={"status": "started"}):
            result = browser_qa._ensure_daemon_running()
        assert result is None

    def test_emit_event_called_on_exhausted_retries(self) -> None:
        """AC-4: BrowserDaemonStartupFailed event emitted on final failure."""
        with mock.patch("yoke_core.domain.browser_client.daemon_running", return_value=False), \
             mock.patch("yoke_core.domain.browser_client.daemon_start", side_effect=RuntimeError("boom")), \
             mock.patch("yoke_core.domain.browser_client.daemon_stop", return_value="stopped"), \
             mock.patch.object(browser_qa, "_collect_daemon_diagnostics", return_value={}), \
             mock.patch.object(browser_qa, "_emit_daemon_startup_failed_event") as mock_emit, \
             mock.patch("yoke_core.domain.browser_qa.time.sleep"):
            result = browser_qa._ensure_daemon_running(item_id=1407, project="yoke")

        assert result is not None
        mock_emit.assert_called_once_with(
            attempt_count=3,
            last_error="boom",
            diagnostics={},
            item_id=1407,
            project="yoke",
        )

    def test_emit_event_failure_does_not_mask_error(self) -> None:
        """Event emission failure should not prevent the error from being returned."""
        with mock.patch("yoke_core.domain.browser_client.daemon_running", return_value=False), \
             mock.patch("yoke_core.domain.browser_client.daemon_start", side_effect=RuntimeError("boom")), \
             mock.patch("yoke_core.domain.browser_client.daemon_stop", return_value="stopped"), \
             mock.patch.object(browser_qa, "_collect_daemon_diagnostics", return_value={}), \
             mock.patch.object(browser_qa, "_emit_daemon_startup_failed_event", side_effect=Exception("emit broken")), \
             mock.patch("yoke_core.domain.browser_qa.time.sleep"):
            result = browser_qa._ensure_daemon_running()

        assert result is not None
        assert "boom" in result

    def test_emit_event_uses_native_runtime_emitter(self) -> None:
        """AC-4: event helper uses the native runtime emitter with item context."""
        env_override = {
            "CODEX_THREAD_ID": "codex-session",
            "YOKE_SESSION_ID": "",
            "CLAUDE_SESSION_ID": "",
        }
        with mock.patch.dict(os.environ, env_override), \
             mock.patch("yoke_core.domain.events.emit_event") as mock_emit:
            browser_qa._emit_daemon_startup_failed_event(
                attempt_count=3,
                last_error="boom",
                diagnostics={
                    "stderr_tail": "tail",
                    "daemon_status": {"status": "crashed"},
                    "daemon_health": {"status": "degraded"},
                },
                item_id=1407,
                project="yoke",
            )

        mock_emit.assert_called_once_with(
            "BrowserDaemonStartupFailed",
            event_kind="system",
            event_type="browser_daemon",
            source_type="backend",
            session_id="codex-session",
            severity="ERROR",
            outcome="failed",
            project="yoke",
            item_id="YOK-1407",
            context={
                "attempt_count": 3,
                "last_error": "boom",
                "diagnostics": {
                    "stderr_tail": "tail",
                    "daemon_status": {"status": "crashed"},
                    "daemon_health": {"status": "degraded"},
                },
            },
        )


class TestCollectDaemonDiagnostics:
    """AC-1: diagnostics collection."""

    def test_collects_stderr_tail(self, tmp_path: Path) -> None:
        """AC-1: stderr log content is captured in diagnostics."""
        stderr_log = tmp_path / ".daemon-stderr.log"
        stderr_log.write_text("line1\nline2\nERROR: port already in use\n")

        with mock.patch("yoke_core.domain.browser_client._browser_dir", return_value=tmp_path), \
             mock.patch("yoke_core.domain.browser_client.daemon_status", return_value={"status": "crashed"}), \
             mock.patch("yoke_core.domain.browser_client.daemon_health", side_effect=RuntimeError("not running")):
            diag = browser_qa._collect_daemon_diagnostics()

        assert "stderr_tail" in diag
        assert "port already in use" in diag["stderr_tail"]
        assert "daemon_status" in diag
        assert diag["daemon_status"]["status"] == "crashed"

    def test_handles_missing_stderr_log(self, tmp_path: Path) -> None:
        """Graceful when no stderr log exists."""
        with mock.patch("yoke_core.domain.browser_client._browser_dir", return_value=tmp_path), \
             mock.patch("yoke_core.domain.browser_client.daemon_status", return_value={"status": "not_running"}), \
             mock.patch("yoke_core.domain.browser_client.daemon_health", side_effect=RuntimeError("not running")):
            diag = browser_qa._collect_daemon_diagnostics()

        assert "stderr_tail" not in diag
        assert diag["daemon_status"]["status"] == "not_running"
