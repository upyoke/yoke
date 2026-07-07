"""Hook-runner session_dispatch coverage for the SessionEnd defense.

Codex SessionStart parity — slim resume block on reactivation.
Legacy-surface guard — old per-event files removed.
Runner lifecycle path exercised end-to-end (Stop/SessionEnd route
through ``_end_session`` with the new chain-end rationale).
AC-5 (workspace export): SessionStart exports ``$YOKE_BOUND_WORKSPACE`` so the
cross-checkout PreToolUse lint and the renderer's ``_atomic_write`` guard
can refuse leaks across linked worktrees.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestLegacySurfaceRetired(unittest.TestCase):
    """AC-23: legacy session-hooks surfaces must not be resurrected."""

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
    """AC-19: slim resume block subprocess routes through the canonical CLI."""

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


class TestSessionWorkspaceExport(unittest.TestCase):
    """SessionStart exports ``YOKE_BOUND_WORKSPACE``."""

    def test_persist_bound_workspace_to_env_file_is_idempotent(self) -> None:
        from runtime.harness.hook_runner.session_workspace import (
            BOUND_WORKSPACE_ENV_VAR,
            persist_bound_workspace_to_env_file,
        )

        with tempfile.TemporaryDirectory() as tmp:
            env_file = os.path.join(tmp, "claude.env")
            workspace = "/Users/x/yoke/.worktrees/YOK-EX1"
            ok1 = persist_bound_workspace_to_env_file(workspace, env_file)
            ok2 = persist_bound_workspace_to_env_file(workspace, env_file)
            self.assertTrue(ok1)
            self.assertTrue(ok2)
            with open(env_file, encoding="utf-8") as fh:
                contents = fh.read()
            self.assertEqual(
                contents.count(f"export {BOUND_WORKSPACE_ENV_VAR}={workspace}\n"),
                1,
                "second persist call must be a no-op when the line already exists",
            )

    def test_persist_bound_workspace_replaces_stale_env_file_value(self) -> None:
        from runtime.harness.hook_runner.session_workspace import (
            BOUND_WORKSPACE_ENV_VAR,
            persist_bound_workspace_to_env_file,
        )

        with tempfile.TemporaryDirectory() as tmp:
            env_file = os.path.join(tmp, "claude.env")
            with open(env_file, "w", encoding="utf-8") as fh:
                fh.write(f"export {BOUND_WORKSPACE_ENV_VAR}=/old/workspace\n")
            workspace = "/Users/x/yoke/.worktrees/YOK-NEW"
            self.assertTrue(persist_bound_workspace_to_env_file(workspace, env_file))
            with open(env_file, encoding="utf-8") as fh:
                contents = fh.read()
            self.assertNotIn("/old/workspace", contents)
            self.assertIn(f"export {BOUND_WORKSPACE_ENV_VAR}={workspace}\n", contents)

    def test_persist_bound_workspace_quotes_shell_sensitive_paths(self) -> None:
        from runtime.harness.hook_runner.session_workspace import (
            BOUND_WORKSPACE_ENV_VAR,
            persist_bound_workspace_to_env_file,
        )

        with tempfile.TemporaryDirectory() as tmp:
            env_file = os.path.join(tmp, "claude.env")
            workspace = "/Users/x/Yoke Worktrees/YOK-SPACE"
            self.assertTrue(persist_bound_workspace_to_env_file(workspace, env_file))
            with open(env_file, encoding="utf-8") as fh:
                contents = fh.read()
            self.assertIn(
                f"export {BOUND_WORKSPACE_ENV_VAR}='/Users/x/Yoke Worktrees/YOK-SPACE'\n",
                contents,
            )

    def test_export_bound_workspace_for_session_sets_environ(self) -> None:
        from runtime.harness.hook_runner.session_workspace import (
            BOUND_WORKSPACE_ENV_VAR,
            export_bound_workspace_for_session,
        )

        prior = os.environ.pop(BOUND_WORKSPACE_ENV_VAR, None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env_file = os.path.join(tmp, "claude.env")
                ok = export_bound_workspace_for_session("/some/workspace", env_file)
                self.assertTrue(ok)
                self.assertEqual(
                    os.environ.get(BOUND_WORKSPACE_ENV_VAR), "/some/workspace"
                )
        finally:
            if prior is None:
                os.environ.pop(BOUND_WORKSPACE_ENV_VAR, None)
            else:
                os.environ[BOUND_WORKSPACE_ENV_VAR] = prior

    def test_claude_session_start_persists_workspace_to_env_file(self) -> None:
        from runtime.harness.hook_runner import session_dispatch
        from runtime.harness.hook_runner.session_workspace import (
            BOUND_WORKSPACE_ENV_VAR,
        )
        from runtime.harness.hook_runner.types import HookContext

        with tempfile.TemporaryDirectory() as tmp:
            env_file = os.path.join(tmp, "claude.env")
            with open(env_file, "w", encoding="utf-8") as fh:
                fh.write("# pre-existing env file\n")
            workspace = "/Users/x/yoke/.worktrees/YOK-EX2"
            db_path = os.path.join(workspace, "data", "yoke.db")
            ctx = HookContext(
                event_name="SessionStart",
                executor_family="claude",
                executor_surface="claude",
                payload={"session_id": "fixture-sid"},
            )
            with mock.patch.dict(os.environ, {"CLAUDE_ENV_FILE": env_file}, clear=False), \
                 mock.patch(
                     "runtime.harness.hook_runner.session_dispatch._root_and_db",
                     return_value=(workspace, db_path),
                 ), \
                 mock.patch(
                     "runtime.harness.hook_runner.session_dispatch._is_yoke_target",
                     return_value=True,
                 ), \
                 mock.patch(
                     "runtime.harness.hook_runner_register._register_from_hook",
                     return_value=("", "claude-code", "anthropic", "claude-opus-4-7", None),
                 ), \
                 mock.patch(
                     "runtime.harness.hook_runner.identity.persist_session_id_to_env_file",
                     return_value=True,
                 ):
                # Exercise the dispatch entry that the runner calls — proves
                # the workspace export lands inside the canonical SessionStart
                # codepath, not via a sibling helper.
                session_dispatch.evaluate(ctx)
                # Inside the patch context: mock.patch.dict snapshots os.environ
                # at __enter__ and restores on __exit__, which would un-set the
                # var we just added. Assert the in-process binding before exit.
                self.assertEqual(
                    os.environ.get(BOUND_WORKSPACE_ENV_VAR),
                    workspace,
                    "SessionStart must set YOKE_BOUND_WORKSPACE in the runner process",
                )
            # Env-file write survives the patch context — verify after exit.
            with open(env_file, encoding="utf-8") as fh:
                contents = fh.read()
            self.assertIn(
                f"export {BOUND_WORKSPACE_ENV_VAR}={workspace}",
                contents,
                "SessionStart must persist YOKE_BOUND_WORKSPACE for subsequent Bash calls",
            )

    def tearDown(self) -> None:
        # Avoid leaking the env var to sibling tests.
        os.environ.pop("YOKE_BOUND_WORKSPACE", None)


if __name__ == "__main__":
    unittest.main()
