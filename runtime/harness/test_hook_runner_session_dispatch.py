"""Hook-runner session_dispatch coverage for the SessionEnd defense.

Codex SessionStart parity — slim resume block on reactivation.
Legacy-surface guard — old per-event files removed.
Runner lifecycle path exercised end-to-end (Stop/SessionEnd route
through ``_end_session`` with the new chain-end rationale).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestLegacySurfaceRetired(unittest.TestCase):
    """Legacy session-hooks surfaces must not be resurrected."""

    def test_legacy_session_hooks_session_end_absent(self) -> None:
        self.assertFalse(
            (REPO_ROOT / "runtime/harness/session_hooks_session_end.py").exists()
        )

    def test_legacy_session_hooks_user_prompt_submit_absent(self) -> None:
        self.assertFalse(
            (REPO_ROOT / "runtime/harness/session_hooks_user_prompt_submit.py").exists()
        )

    def test_legacy_session_hooks_front_door_absent(self) -> None:
        self.assertFalse(
            (REPO_ROOT / "runtime/harness/session_hooks.py").exists()
        )

    def test_legacy_codex_session_start_absent(self) -> None:
        self.assertFalse(
            (REPO_ROOT / "runtime/harness/codex/codex_hooks_session_start.py").exists()
        )

    def test_post_runner_session_dispatch_present(self) -> None:
        self.assertTrue(
            (REPO_ROOT / "runtime/harness/hook_runner/session_dispatch.py").exists()
        )
        self.assertTrue(
            (REPO_ROOT / "runtime/harness/hook_runner/resume_block_dispatch.py").exists()
        )


class TestOrientationProjectAuthority(unittest.TestCase):
    """Session orientation must not teach DB repo paths as client checkouts."""

    def test_orientation_does_not_render_project_repo_path_map(self) -> None:
        from runtime.harness.hook_runner import session_dispatch

        with mock.patch(
            "runtime.harness.hook_runner.session_dispatch._bootstrap_lines",
            return_value=["Read before editing:", "- AGENTS.md"],
        ), mock.patch(
            "runtime.harness.hook_runner.session_dispatch._git_line",
            return_value="",
        ):
            rendered = session_dispatch._render_claude_orientation(
                "sess-orient",
                "/Users/alice/yoke",
                "",
                "claude-code",
                "claude-opus",
            )

        self.assertNotIn("Project repos", rendered)
        self.assertNotIn("repo_path", rendered)
        self.assertIn("Your Session: sess-orient", rendered)


class TestEndSessionCommand(unittest.TestCase):
    """Stop and SessionEnd both use the non-destructive empty-session cleanup."""

    def test_session_end_cleanup_uses_domain_end_if_empty(self) -> None:
        from runtime.harness.hook_runner import session_end_cleanup

        class FakeConn:
            def close(self) -> None:
                pass

        captured = {}

        def fake_cleanup(_conn, session_id):
            captured["session_id"] = session_id

        ok = session_end_cleanup.run_session_end_cleanup(
            "/repo", "sess-stop", executor="codex", event_source="Stop",
            _connect=lambda _timeout_ms: FakeConn(), _cleanup=fake_cleanup,
        )

        self.assertTrue(ok)
        self.assertEqual(captured["session_id"], "sess-stop")

    def test_stop_skips_model_refresh_and_runs_cleanup(self) -> None:
        from runtime.harness.hook_runner import session_dispatch
        from runtime.harness.hook_runner.types import HookContext

        ctx = HookContext(
            event_name="Stop",
            executor_family="codex",
            executor_surface="codex",
            payload={
                "session_id": "sess-stop",
                "transcript_path": "/tmp/transcript.jsonl",
            },
        )
        with mock.patch(
            "runtime.harness.hook_runner.session_dispatch._root_and_db",
            return_value=("/Users/x/yoke", "/Users/x/yoke/data/yoke.db"),
        ), mock.patch(
            "runtime.harness.hook_runner.session_dispatch._is_yoke_target",
            return_value=True,
        ), mock.patch(
            "runtime.harness.hook_runner.telemetry.resolve_direct_session_id",
            return_value="sess-stop",
        ), mock.patch(
            "runtime.harness.hook_runner.telemetry.refresh_session_model_if_placeholder",
        ) as refresh, mock.patch(
            "runtime.harness.hook_runner.session_dispatch._end_session_if_empty",
        ) as cleanup:
            decision = session_dispatch.evaluate(ctx)

        self.assertEqual(decision.audit_fields["stdout"], "{}\n")
        refresh.assert_not_called()
        cleanup.assert_called_once_with(
            "/Users/x/yoke", "sess-stop",
            executor="codex", event_source="Stop",
        )


class TestResumeBlockDispatchSubprocess(unittest.TestCase):
    """Slim resume block subprocess routes through the canonical CLI."""

    def test_render_invokes_sessions_resume_block_module(self) -> None:
        from runtime.harness.hook_runner import resume_block_dispatch

        captured_cmd: list[list[str]] = []

        def _fake_run(cmd, **_kw):
            captured_cmd.append(cmd)

            class _R:
                returncode = 0
                stdout = "> resume block\n"
                stderr = ""

            return _R()

        with mock.patch(
            "runtime.harness.hook_runner.resume_block_dispatch.subprocess.run",
            side_effect=_fake_run,
        ):
            result = resume_block_dispatch.render(
                "/repo", "sess-r", "UserPromptSubmit",
            )
        self.assertEqual(result, "> resume block\n")
        self.assertTrue(captured_cmd)
        cmd = captured_cmd[0]
        self.assertIn("yoke_core.domain.sessions_resume_block", cmd)
        self.assertIn("--session-id", cmd)
        self.assertIn("sess-r", cmd)
        self.assertIn("--harness-event", cmd)
        self.assertIn("UserPromptSubmit", cmd)

    def test_render_returns_empty_when_session_id_missing(self) -> None:
        from runtime.harness.hook_runner import resume_block_dispatch

        with mock.patch(
            "runtime.harness.hook_runner.resume_block_dispatch.subprocess.run",
        ) as mocked:
            result = resume_block_dispatch.render(
                "/repo", "", "SessionStart",
            )
        self.assertEqual(result, "")
        mocked.assert_not_called()

    def test_render_returns_empty_on_nonzero_exit(self) -> None:
        from runtime.harness.hook_runner import resume_block_dispatch

        class _R:
            returncode = 7
            stdout = "ignored"
            stderr = ""

        with mock.patch(
            "runtime.harness.hook_runner.resume_block_dispatch.subprocess.run",
            return_value=_R(),
        ):
            result = resume_block_dispatch.render(
                "/repo", "sess-r", "UserPromptSubmit",
            )
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
