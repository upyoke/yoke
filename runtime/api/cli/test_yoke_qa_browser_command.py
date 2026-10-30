"""Tests for Browser substrate tooling and the retired aggregate token."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from yoke_cli.commands.qa_browser import qa_browser_screenshot, qa_browser_step
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


pytestmark = pytest.mark.usefixtures("bound_project_context")


class TestTokenRouting:
    def test_aggregate_run_token_does_not_resolve(self):
        resolved = resolve_tool_shaped(["qa", "browser", "run", "--item", "X-1"])
        assert resolved is None

    def test_screenshot_token_resolves(self):
        resolved = resolve_tool_shaped(
            ["qa", "browser", "screenshot", "https://x", "--output", "/tmp/a.png"]
        )
        assert resolved is not None
        adapter, rest = resolved
        assert adapter is qa_browser_screenshot
        assert rest == ["https://x", "--output", "/tmp/a.png"]

    def test_step_token_resolves(self):
        resolved = resolve_tool_shaped(
            ["qa", "browser", "step", "--base-url", "https://x", "--step-json", "{}"]
        )
        assert resolved is not None
        adapter, rest = resolved
        assert adapter is qa_browser_step
        assert rest == ["--base-url", "https://x", "--step-json", "{}"]


class TestScreenshotAdapter:
    def _run(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = qa_browser_screenshot(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_missing_output_flag_is_usage_error(self):
        rc, _out, _err = self._run("https://x.example/route")
        assert rc == 2

    def test_daemon_unavailable_exits_two_with_teaching(self):
        with patch(
            "yoke_harness.browser_qa_daemon.ensure_daemon_running",
            return_value="daemon start failed after retries",
        ):
            rc, _out, err = self._run(
                "https://x.example/route",
                "--output",
                "/tmp/shot.png",
            )
        assert rc == 2
        assert "browser daemon unavailable" in err

    def test_capture_passes_parsed_args_and_prints_json(self):
        captured = {}

        def fake_snapshot(url, *, annotate, output_path, viewport):
            captured.update(
                url=url,
                annotate=annotate,
                output_path=output_path,
                viewport=viewport,
            )
            return {"ok": True, "outputPath": output_path}

        with (
            patch(
                "yoke_harness.browser_qa_daemon.ensure_daemon_running",
                return_value=None,
            ),
            patch(
                "yoke_harness.browser_client.snapshot_screenshot",
                side_effect=fake_snapshot,
            ),
        ):
            rc, out, _err = self._run(
                "https://x.example/route",
                "--output",
                "/tmp/shot.png",
                "--viewport",
                "1280x720",
                "--annotate",
            )
        assert rc == 0
        assert captured == {
            "url": "https://x.example/route",
            "annotate": True,
            "output_path": "/tmp/shot.png",
            "viewport": "1280x720",
        }
        assert json.loads(out)["outputPath"] == "/tmp/shot.png"

    def test_project_flag_selects_the_authorized_profile(self):
        """The daemon opens the same project's profile `authorize` signed in."""
        with (
            patch(
                "yoke_harness.browser_qa_daemon.ensure_daemon_running",
                return_value=None,
            ) as ensure,
            patch(
                "yoke_harness.browser_client.snapshot_screenshot",
                return_value={"ok": True},
            ),
        ):
            rc, _out, _err = self._run(
                "https://x.example/route",
                "--output",
                "/tmp/shot.png",
                "--project",
                "acme",
            )
        assert rc == 0
        ensure.assert_called_once_with("acme", None)

    def test_capture_runtime_error_exits_one(self):
        with (
            patch(
                "yoke_harness.browser_qa_daemon.ensure_daemon_running",
                return_value=None,
            ),
            patch(
                "yoke_harness.browser_client.snapshot_screenshot",
                side_effect=RuntimeError("daemon http 500"),
            ),
        ):
            rc, _out, err = self._run(
                "https://x.example/route",
                "--output",
                "/tmp/shot.png",
            )
        assert rc == 1
        assert "daemon http 500" in err


class TestStepAdapter:
    def _run(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = qa_browser_step(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_invalid_step_json_is_usage_error(self):
        rc, _out, err = self._run("--base-url", "https://x.example", "--step-json", "[")
        assert rc == 2
        assert "invalid step JSON" in err

    @pytest.mark.parametrize(
        "declared,expected",
        [
            (120000, 135),
            (60001, 75.001),
            (0, 30),
            (-1, 30),
            (True, 30),
            (None, 30),
            (float("inf"), 30),
            (float("nan"), 30),
        ],
    )
    def test_public_step_transport_honors_action_budget(self, declared, expected):
        calls = []

        def request(path, body, **kwargs):
            calls.append((path, body, kwargs))
            return {"data": {"pageId": "exploratory"}, "success": True}

        with (
            patch(
                "yoke_harness.browser_qa_daemon.ensure_daemon_running",
                return_value=None,
            ),
            patch("yoke_harness.browser_client.daemon_request", side_effect=request),
        ):
            rc, out, _err = self._run(
                "--base-url",
                "https://x.example",
                "--step-json",
                json.dumps(
                    {"action": "click", "target": "#submit", "timeout_ms": declared}
                ),
            )
        assert rc == 0
        assert json.loads(out)["success"] is True
        assert [call[0] for call in calls] == ["/api/exec/page", "/api/exec/step"]
        assert calls[1][2]["timeout"] == expected

    @pytest.mark.parametrize("page", [None, "review"])
    def test_step_passes_agent_selected_payload_and_prints_json(self, page):
        captured = {}

        def fake_execute(step, base_url, *, output_dir, page_id):
            captured.update(
                step=step,
                base_url=base_url,
                output_dir=output_dir,
                page_id=page_id,
            )
            return {"ok": True, "url": base_url}

        with (
            patch(
                "yoke_harness.browser_qa_daemon.ensure_daemon_running",
                return_value=None,
            ),
            patch(
                "yoke_harness.browser_client.ensure_page",
                return_value=page or "exploratory",
            ) as ensure_page,
            patch(
                "yoke_harness.browser_client.execute_step",
                side_effect=fake_execute,
            ),
        ):
            rc, out, _err = self._run(
                "--base-url",
                "https://x.example",
                "--step-json",
                '{"action":"click","selector":"#continue"}',
                "--output-dir",
                "/tmp/browser-proof",
                *(["--page", page] if page is not None else []),
            )
        ensure_page.assert_called_once_with(page or "exploratory")
        assert rc == 0
        assert captured == {
            "step": {"action": "click", "selector": "#continue"},
            "base_url": "https://x.example",
            "output_dir": "/tmp/browser-proof",
            "page_id": page or "exploratory",
        }
        assert json.loads(out) == {"ok": True, "url": "https://x.example"}

    @pytest.mark.parametrize("page", ["", "   "])
    def test_blank_page_refuses_before_daemon_start(self, page):
        with patch("yoke_harness.browser_qa_daemon.ensure_daemon_running") as start:
            rc, _out, err = self._run(
                "--base-url",
                "https://x.example",
                "--step-json",
                "{}",
                "--page",
                page,
            )
        assert rc == 2
        assert "page_name_blank" in err
        start.assert_not_called()

    def test_named_pages_reach_page_and_step_requests(self):
        calls = []

        def request(path, body, **kwargs):
            calls.append((path, body))
            return {"data": {"pageId": body["pageId"]}, "success": True}

        with (
            patch(
                "yoke_harness.browser_qa_daemon.ensure_daemon_running",
                return_value=None,
            ),
            patch("yoke_harness.browser_client.daemon_request", side_effect=request),
        ):
            for page in ("a", "b"):
                rc, _out, _err = self._run(
                    "--base-url",
                    "https://x.example",
                    "--step-json",
                    '{"action":"navigate","route":"/"}',
                    "--page",
                    page,
                )
                assert rc == 0
        for endpoint in ("/api/exec/page", "/api/exec/step"):
            assert [body["pageId"] for path, body in calls if path == endpoint] == [
                "a",
                "b",
            ]


class TestOperationInventory:
    def test_case_and_browser_tokens_are_permanent_tool_shaped(self):
        from yoke_cli import operation_inventory as inv

        for shell_form in (
            "yoke qa case run",
            "yoke qa browser screenshot",
            "yoke qa browser step",
        ):
            entry = inv.lookup(shell_form)
            assert entry is not None, shell_form
            assert entry.status == inv.PERMANENT
            assert entry.reason == inv.REASON_TOOL_SHAPED
        assert inv.lookup("yoke qa browser run") is None
