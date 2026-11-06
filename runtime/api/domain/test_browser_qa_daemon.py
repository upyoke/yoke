"""Browser QA — daemon retry and diagnostics suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from yoke_core.domain import browser_qa
from yoke_harness.browser_daemon_profile import profile_scope as profile_scope_for_test
from runtime.api.cli.browser_profile_daemons_live_test_support import (
    daemon_runtime as daemon_runtime,
)

import pytest

pytestmark = pytest.mark.usefixtures("bound_project_context")


# ---------------------------------------------------------------------------
# Daemon auto-retry and diagnostics
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def private_check_scope(tmp_path):
    from yoke_harness.browser_daemon_profile import profile_scope

    with profile_scope(tmp_path / "check-profile"):
        yield


class TestDaemonRetry:
    """_ensure_daemon_running performs bounded auto-recovery."""

    def test_retry_succeeds_on_second_attempt(self) -> None:
        """If a retry succeeds, execution continues normally."""
        call_count = 0

        def _fake_start(**_kw: Any) -> Dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("port in use")
            return {"status": "started"}

        with (
            mock.patch("yoke_core.domain.browser_qa.time.sleep"),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_running", return_value=False
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_start", side_effect=_fake_start
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_stop", return_value="stopped"
            ),
        ):
            result = browser_qa._ensure_daemon_running()

        assert result is None  # success
        assert call_count == 2  # first failed, second succeeded

    def test_retry_exhausted_returns_error_with_diagnostics(self) -> None:
        """After max retries, returns error with diagnostics."""
        with (
            mock.patch(
                "yoke_core.domain.browser_client.daemon_running", return_value=False
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_start",
                side_effect=RuntimeError("persistent failure"),
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_stop", return_value="stopped"
            ),
            mock.patch.object(
                browser_qa,
                "_collect_daemon_diagnostics",
                return_value={
                    "log_tail": "Error: EADDRINUSE",
                    "daemon_status": {"status": "crashed"},
                    "daemon_health": {"status": "degraded"},
                },
            ),
            mock.patch.object(
                browser_qa, "_emit_daemon_startup_failed_event"
            ) as mock_emit,
            mock.patch("yoke_core.domain.browser_qa.time.sleep"),
        ):
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
        """Each retry attempt and outcome are logged."""
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

        with (
            mock.patch.object(browser_qa, "_log", side_effect=_capture_log),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_running", return_value=False
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_start", side_effect=_fake_start
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_stop", return_value="stopped"
            ),
            mock.patch("yoke_core.domain.browser_qa.time.sleep"),
        ):
            result = browser_qa._ensure_daemon_running()

        assert result is None  # third attempt succeeds
        # Check that retry attempts were logged
        retry_msgs = [m for m in logged_messages if "Retry" in m or "attempt" in m]
        assert len(retry_msgs) >= 2  # at least the two retry log lines

    def test_daemon_already_running_skips_retry(self) -> None:
        """Baseline: if daemon is already running, no retry logic executes."""
        with (
            mock.patch(
                "yoke_core.domain.browser_client.daemon_start",
                return_value={"status": "already_running"},
            ) as start,
            mock.patch(
                "yoke_core.domain.browser_client.daemon_stop",
            ) as stop,
        ):
            result = browser_qa._ensure_daemon_running()
        assert result is None
        start.assert_called_once()
        stop.assert_not_called()

    def test_first_attempt_success_skips_retry(self) -> None:
        """Baseline: if first start succeeds, no retry logic executes."""
        with (
            mock.patch(
                "yoke_core.domain.browser_client.daemon_running", return_value=False
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_start",
                return_value={"status": "started"},
            ),
        ):
            result = browser_qa._ensure_daemon_running()
        assert result is None

    def test_emit_event_called_on_exhausted_retries(self) -> None:
        """BrowserDaemonStartupFailed event emitted on final failure."""
        with (
            mock.patch(
                "yoke_core.domain.browser_client.daemon_running", return_value=False
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_start",
                side_effect=RuntimeError("boom"),
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_stop", return_value="stopped"
            ),
            mock.patch.object(
                browser_qa, "_collect_daemon_diagnostics", return_value={}
            ),
            mock.patch.object(
                browser_qa, "_emit_daemon_startup_failed_event"
            ) as mock_emit,
            mock.patch("yoke_core.domain.browser_qa.time.sleep"),
        ):
            result = browser_qa._ensure_daemon_running(subject=1407, project="yoke")

        assert result is not None
        mock_emit.assert_called_once_with(
            attempt_count=3,
            last_error="boom",
            diagnostics={},
            subject=1407,
            project="yoke",
        )

    def test_emit_event_failure_does_not_mask_error(self) -> None:
        """Event emission failure should not prevent the error from being returned."""
        with (
            mock.patch(
                "yoke_core.domain.browser_client.daemon_running", return_value=False
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_start",
                side_effect=RuntimeError("boom"),
            ),
            mock.patch(
                "yoke_core.domain.browser_client.daemon_stop", return_value="stopped"
            ),
            mock.patch.object(
                browser_qa, "_collect_daemon_diagnostics", return_value={}
            ),
            mock.patch.object(
                browser_qa,
                "_emit_daemon_startup_failed_event",
                side_effect=Exception("emit broken"),
            ),
            mock.patch("yoke_core.domain.browser_qa.time.sleep"),
        ):
            result = browser_qa._ensure_daemon_running()

        assert result is not None
        assert "boom" in result


def test_same_identity_slow_checks_keep_private_pids_and_pages(
    daemon_runtime, tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from http.server import ThreadingHTTPServer
    from threading import Barrier, Thread
    from yoke_harness import browser_client
    from yoke_harness.browser_check_profile import check_scope
    from yoke_harness.browser_daemon_profile import selected_profile
    from runtime.api.cli.browser_profile_daemons_live_test_support import (
        ProbeHandler,
    )

    source = tmp_path / "authoritative"
    source.mkdir()
    monkeypatch.setattr(
        "yoke_harness.browser_check_profile.resolve_authorized_profile",
        lambda *a, **k: (source, "authorized"),
    )
    monkeypatch.setattr(
        "yoke_harness.browser_check_profile.machine_config.yoke_home",
        lambda: tmp_path / "machine",
    )
    barrier = Barrier(2)
    paths = []

    with ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler) as server:
        Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}"
        # Seed the authoritative profile as an explicit sign-in would.
        browser_client.daemon_start(profile_dir=str(source))
        with profile_scope_for_test(source):
            page = browser_client.ensure_page("sign-in")
            browser_client.execute_step(
                {"action": "navigate", "route": "/alpha"}, url, page_id=page
            )
        browser_client.daemon_stop(profile_dir=str(source))

        def check(index):
            with check_scope("fixture", "admin"):
                profile = selected_profile()
                paths.append(Path(profile))
                assert (
                    browser_qa._ensure_daemon_running(
                        project="fixture", identity="admin"
                    )
                    is None
                )
                pid = browser_client.daemon_status()["pid"]
                page = browser_client.ensure_page("check")
                browser_client.execute_step(
                    {"action": "navigate", "route": f"/check-{index}"},
                    url,
                    page_id=page,
                )
                barrier.wait(timeout=20)
                if index == 0:
                    response = browser_client.execute_step(
                        {"action": "delay", "duration_ms": 1500}, url, page_id=page
                    )
                    assert response["success"], response
                # The other check's startup/retry cannot reset this pid or page.
                assert (
                    browser_qa._ensure_daemon_running(
                        project="fixture", identity="admin"
                    )
                    is None
                )
                assert browser_client.daemon_status()["pid"] == pid
                response = browser_client.execute_step(
                    {
                        "action": "assert",
                        "target": "body",
                        "check": "text_contains",
                        "expected": f"check-{index}; cookie=profile=alpha",
                    },
                    url,
                    page_id=page,
                )
                assert response["success"], response
                return pid

        with ThreadPoolExecutor(max_workers=2) as pool:
            pids = list(pool.map(check, [0, 1]))
        assert pids[0] != pids[1]
        assert all(not path.exists() for path in paths)
        assert source.is_dir()
        assert (
            browser_client.daemon_status(profile_dir=str(source))["status"] != "running"
        )
        server.shutdown()
