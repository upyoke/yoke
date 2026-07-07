"""Tests for the tool-shaped ``yoke qa browser`` family routing
(``run`` token resolution, the ``screenshot`` manual-fallback capture)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_cli.commands.qa_browser import (
    qa_browser_run,
    qa_browser_screenshot,
)
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


class TestTokenRouting:
    def test_run_token_resolves(self):
        resolved = resolve_tool_shaped(["qa", "browser", "run", "--item", "X-1"])
        assert resolved is not None
        adapter, rest = resolved
        assert adapter is qa_browser_run
        assert rest == ["--item", "X-1"]

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
            "yoke_harness.browser_qa.ensure_daemon_running",
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
            "yoke_harness.browser_qa.ensure_daemon_running",
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
            "yoke_harness.browser_qa.ensure_daemon_running",
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


class TestRunAdapter:
    def _run(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = qa_browser_run(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_run_auto_added_project_flag_reaches_context_dispatch_target(self):
        calls = []

        def fake_dispatcher(*, function_id, target, payload, actor):
            calls.append(
                (
                    function_id,
                    target.kind,
                    target.item_ref,
                    target.project_id,
                    payload,
                    actor.session_id,
                )
            )
            return FunctionCallResponse(
                success=True,
                function=function_id,
                version="v1",
                result={"item_id": 1732, "requirements": []},
            )

        with patch(
            "yoke_cli.commands.qa_browser.ensure_handlers_loaded",
            return_value=None,
        ), patch(
            "yoke_cli.commands.qa_browser.call_dispatcher",
            side_effect=fake_dispatcher,
        ):
            rc, out, _err = self._run(
                "--item", "BUZ-1732", "--project", "buzz",
                "--base-url", "http://127.0.0.1:3000",
            )

        assert rc == 2
        assert json.loads(out) == {
            "verdict": "pass",
            "runs": [],
            "note": "no_browser_requirements",
        }
        assert [
            (function, kind, item_ref, project_id, payload)
            for function, kind, item_ref, project_id, payload, _ in calls
        ] == [
            (
                "qa.browser_context.get",
                "item",
                "BUZ-1732",
                "buzz",
                {"project": "buzz"},
            ),
        ]


class TestOperationInventory:
    def test_browser_tokens_are_permanent_tool_shaped(self):
        from yoke_cli import operation_inventory as inv

        for shell_form in (
            "yoke qa browser run",
            "yoke qa browser screenshot",
        ):
            entry = inv.lookup(shell_form)
            assert entry is not None, shell_form
            assert entry.status == inv.PERMANENT
            assert entry.reason == inv.REASON_TOOL_SHAPED
