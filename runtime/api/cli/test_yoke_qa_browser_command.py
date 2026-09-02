"""Tests for Browser substrate tooling and the retired aggregate token."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.commands.qa_browser import qa_browser_screenshot, qa_browser_step
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

    def test_project_flag_selects_the_authorized_profile(self):
        """The daemon opens the same project's profile `authorize` signed in."""
        with patch(
            "yoke_harness.browser_qa_daemon.ensure_daemon_running",
            return_value=None,
        ) as ensure, patch(
            "yoke_harness.browser_client.snapshot_screenshot",
            return_value={"ok": True},
        ):
            rc, _out, _err = self._run(
                "https://x.example/route", "--output", "/tmp/shot.png",
                "--project", "acme",
            )
        assert rc == 0
        ensure.assert_called_once_with("acme")

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


class TestStepAdapter:
    def _run(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = qa_browser_step(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_invalid_step_json_is_usage_error(self):
        rc, _out, err = self._run(
            "--base-url", "https://x.example", "--step-json", "["
        )
        assert rc == 2
        assert "invalid step JSON" in err

    def test_step_passes_agent_selected_payload_and_prints_json(self):
        captured = {}

        def fake_execute(step, base_url, *, output_dir):
            captured.update(step=step, base_url=base_url, output_dir=output_dir)
            return {"ok": True, "url": base_url}

        with patch(
            "yoke_harness.browser_qa_daemon.ensure_daemon_running",
            return_value=None,
        ), patch(
            "yoke_harness.browser_client.execute_step",
            side_effect=fake_execute,
        ):
            rc, out, _err = self._run(
                "--base-url", "https://x.example",
                "--step-json", '{"action":"click","selector":"#continue"}',
                "--output-dir", "/tmp/browser-proof",
            )
        assert rc == 0
        assert captured == {
            "step": {"action": "click", "selector": "#continue"},
            "base_url": "https://x.example",
            "output_dir": "/tmp/browser-proof",
        }
        assert json.loads(out) == {"ok": True, "url": "https://x.example"}


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
