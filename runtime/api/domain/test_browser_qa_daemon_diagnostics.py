"""Browser startup telemetry and bounded failure diagnostics."""

import os
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import browser_qa
from yoke_harness.browser_client_readiness import DAEMON_LOG_NAME

pytestmark = pytest.mark.usefixtures("bound_project_context")


class TestStartupTelemetry:
    def test_emit_event_uses_native_runtime_emitter(
        self,
        harness_family,
    ) -> None:
        """Event helper uses the native runtime emitter with item context."""
        harness_family("codex")
        env_override = {
            "CODEX_THREAD_ID": "codex-session",
            "CODEX_SESSION_ID": "",
            "YOKE_SESSION_ID": "",
            "CLAUDE_CODE_SESSION_ID": "",
        }
        with (
            mock.patch.dict(os.environ, env_override),
            mock.patch("yoke_core.domain.events.emit_event") as mock_emit,
        ):
            browser_qa._emit_daemon_startup_failed_event(
                attempt_count=3,
                last_error="boom",
                diagnostics={
                    "log_tail": "tail",
                    "daemon_status": {"status": "crashed"},
                    "daemon_health": {"status": "degraded"},
                },
                subject=1407,
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
            item_id=1407,
            context={
                "attempt_count": 3,
                "last_error": "boom",
                "diagnostics": {
                    "log_tail": "tail",
                    "daemon_status": {"status": "crashed"},
                    "daemon_health": {"status": "degraded"},
                },
                "subject": 1407,
            },
        )


class TestCollectDaemonDiagnostics:
    """Diagnostics collection."""

    def test_collects_daemon_log_tail(self, tmp_path: Path) -> None:
        """Daemon log content is captured in diagnostics."""
        from yoke_harness.browser_daemon_profile import state_file_path

        daemon_log = state_file_path(tmp_path, "").parent / DAEMON_LOG_NAME
        daemon_log.parent.mkdir(parents=True)
        daemon_log.write_text("line1\nline2\nERROR: port already in use\n")

        with (
            mock.patch(
                "yoke_core.domain.browser_client._browser_dir", return_value=tmp_path
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_status",
                return_value={"status": "crashed"},
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_health",
                side_effect=RuntimeError("not running"),
            ),
        ):
            diag = browser_qa._collect_daemon_diagnostics()

        assert "log_tail" in diag
        assert "port already in use" in diag["log_tail"]
        assert "daemon_status" in diag
        assert diag["daemon_status"]["status"] == "crashed"

    def test_handles_missing_daemon_log(self, tmp_path: Path) -> None:
        """Graceful when no daemon log exists."""
        with (
            mock.patch(
                "yoke_core.domain.browser_client._browser_dir", return_value=tmp_path
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_status",
                return_value={"status": "not_running"},
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_health",
                side_effect=RuntimeError("not running"),
            ),
        ):
            diag = browser_qa._collect_daemon_diagnostics()

        assert "log_tail" not in diag
        assert diag["daemon_status"]["status"] == "not_running"
