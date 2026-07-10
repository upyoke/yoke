"""Ephemeral deployment verification executor behavior."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from yoke_core.domain.ephemeral_substrate import slugify_branch
from yoke_core.tools import executors


class ExecEphemeralVerifyTests(unittest.TestCase):
    def _success_run(self) -> dict:
        return {
            "id": 9999,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-04-11T00:00:00Z",
        }

    def test_success_prints_ephemeral_url(self) -> None:
        with mock.patch.object(
            executors, "_gh_runs_for_workflow", return_value=self._success_run()
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = executors.exec_ephemeral_verify(
                    "org/repo",
                    "YOK-1369",
                    "deploy.yml",
                    "previews.yoke.test",
                    project="buzz",
                )
        self.assertEqual(rc, 0)
        self.assertIn(
            "EPHEMERAL_URL=https://yok-1369.previews.yoke.test",
            buf.getvalue(),
        )

    def test_failure_when_run_not_found(self) -> None:
        with mock.patch.object(executors, "_gh_runs_for_workflow", return_value=None):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_ephemeral_verify(
                    "org/repo",
                    "YOK-1369",
                    "deploy.yml",
                    "previews.yoke.test",
                    commit_sha="abc123",
                    project="buzz",
                )
        self.assertEqual(rc, 1)
        self.assertIn("No ephemeral deploy run found", buf.getvalue())

    def test_failure_when_run_in_progress(self) -> None:
        pending = {
            "id": 1,
            "status": "in_progress",
            "conclusion": "",
            "created_at": "",
        }
        with mock.patch.object(executors, "_gh_runs_for_workflow", return_value=pending):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_ephemeral_verify(
                    "org/repo", "YOK-1369", "deploy.yml", "example.test",
                    project="buzz",
                )
        self.assertEqual(rc, 1)
        self.assertIn("still in_progress", buf.getvalue())

    def test_failure_when_conclusion_not_success(self) -> None:
        failed = {
            "id": 2,
            "status": "completed",
            "conclusion": "failure",
            "created_at": "",
        }
        with mock.patch.object(executors, "_gh_runs_for_workflow", return_value=failed):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_ephemeral_verify(
                    "org/repo", "YOK-1369", "deploy.yml", "example.test",
                    project="buzz",
                )
        self.assertEqual(rc, 1)
        self.assertIn("concluded with: failure", buf.getvalue())

    def test_rejects_missing_branch_and_sha(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = executors.exec_ephemeral_verify(
                "org/repo", "", "deploy.yml", "example.test",
                project="buzz",
            )
        self.assertEqual(rc, 1)
        self.assertIn("at least one of", buf.getvalue())

    def test_rejects_missing_domain(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = executors.exec_ephemeral_verify(
                "org/repo", "YOK-1369", "deploy.yml", "",
                project="buzz",
            )
        self.assertEqual(rc, 1)
        self.assertIn("domain not provided", buf.getvalue())

    def test_lookup_resolves_explicit_project_and_repo(self) -> None:
        run = self._success_run()
        with mock.patch.object(
            executors, "resolve_token", return_value="ghs_test",
        ) as resolve, mock.patch.object(
            executors, "latest_workflow_run", return_value=run,
        ) as latest:
            result = executors._gh_runs_for_workflow(
                "org/repo", "deploy.yml", project="buzz", branch="feature",
            )

        self.assertEqual(result, run)
        resolve.assert_called_once_with("buzz", "org/repo")
        latest.assert_called_once_with(
            "org/repo", "deploy.yml", branch="feature", token="ghs_test",
        )

    def test_transport_failure_is_not_reported_as_no_run(self) -> None:
        from yoke_core.domain.gh_rest_transport import RestNetworkError

        with mock.patch.object(
            executors,
            "_gh_runs_for_workflow",
            side_effect=RestNetworkError("offline"),
        ):
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = executors.exec_ephemeral_verify(
                    "org/repo", "feature", "deploy.yml", "example.test",
                    project="buzz",
                )

        self.assertEqual(rc, 1)
        self.assertIn("lookup failed", buf.getvalue())
        self.assertNotIn("No ephemeral deploy run found", buf.getvalue())


class SlugifyTests(unittest.TestCase):
    def test_matches_legacy_shell_slug(self) -> None:
        self.assertEqual(slugify_branch("YOK-1369"), "yok-1369")
        self.assertEqual(slugify_branch("feature/foo bar"), "feature-foo-bar")
        self.assertEqual(slugify_branch("--X--Y--"), "x-y")
