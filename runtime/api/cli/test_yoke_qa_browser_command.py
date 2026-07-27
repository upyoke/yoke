"""Tests for Browser substrate tooling and the retired aggregate token."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.commands.qa_browser import qa_browser_screenshot
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


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
                "https://x.example/route", "--output", "/tmp/shot.png",
            )
        assert rc == 2
        assert "browser daemon unavailable" in err

    def test_capture_passes_parsed_args_and_prints_json(self):
        captured = {}

        def fake_snapshot(url, *, annotate, output_path, viewport):
            captured.update(
                url=url, annotate=annotate,
                output_path=output_path, viewport=viewport,
            )
            return {"ok": True, "outputPath": output_path}

        with patch(
            "yoke_harness.browser_qa_daemon.ensure_daemon_running",
            return_value=None,
        ), patch(
            "yoke_harness.browser_client.snapshot_screenshot",
            side_effect=fake_snapshot,
        ):
            rc, out, _err = self._run(
                "https://x.example/route", "--output", "/tmp/shot.png",
                "--viewport", "1280x720", "--annotate",
            )
        assert rc == 0
        assert captured == {
            "url": "https://x.example/route",
            "annotate": True,
            "output_path": "/tmp/shot.png",
            "viewport": "1280x720",
        }
        assert json.loads(out)["outputPath"] == "/tmp/shot.png"

    def test_capture_runtime_error_exits_one(self):
        with patch(
            "yoke_harness.browser_qa_daemon.ensure_daemon_running",
            return_value=None,
        ), patch(
            "yoke_harness.browser_client.snapshot_screenshot",
            side_effect=RuntimeError("daemon http 500"),
        ):
            rc, _out, err = self._run(
                "https://x.example/route", "--output", "/tmp/shot.png",
            )
        assert rc == 1
        assert "daemon http 500" in err


class TestOperationInventory:
    def test_case_and_screenshot_tokens_are_permanent_tool_shaped(self):
        from yoke_cli import operation_inventory as inv

        for shell_form in (
            "yoke qa case run",
            "yoke qa browser screenshot",
        ):
            entry = inv.lookup(shell_form)
            assert entry is not None, shell_form
            assert entry.status == inv.PERMANENT
            assert entry.reason == inv.REASON_TOOL_SHAPED
        assert inv.lookup("yoke qa browser run") is None
