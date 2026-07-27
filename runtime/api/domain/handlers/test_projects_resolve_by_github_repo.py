"""Unit tests for the ``projects.resolve_by_github_repo`` handler."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.api.domain.handlers.projects_handler_test_support import (
    project_request as _request,
    project_row as _project_row,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import projects_get


class TestProjectsResolveByGithubRepo(unittest.TestCase):
    def test_returns_visible_project_for_matching_repo(self):
        class _Conn:
            def close(self):
                pass

        row = _project_row(
            id=37,
            slug="externalwebapp",
            github_repo="example-org/externalwebapp",
        )
        with (
            patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
            patch("yoke_core.domain.db_helpers.query_rows", return_value=[row]),
        ):
            outcome = projects_get.handle_projects_resolve_by_github_repo(
                _request(
                    function="projects.resolve_by_github_repo",
                    payload={
                        "github_repo": ("git@github.com:Example-Org/ExternalWebapp.git")
                    },
                ),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            outcome.result_payload["github_repo"],
            "example-org/externalwebapp",
        )
        self.assertEqual(outcome.result_payload["row"]["id"], 37)
        self.assertEqual(outcome.result_payload["row"]["slug"], "externalwebapp")

    def test_returns_not_found_when_no_project_has_repo(self):
        class _Conn:
            def close(self):
                pass

        row = _project_row(
            id=37,
            slug="externalwebapp",
            github_repo="example-org/externalwebapp",
        )
        with (
            patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
            patch("yoke_core.domain.db_helpers.query_rows", return_value=[row]),
        ):
            outcome = projects_get.handle_projects_resolve_by_github_repo(
                _request(
                    function="projects.resolve_by_github_repo",
                    payload={"github_repo": "owner/other"},
                ),
            )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")

    def test_returns_permission_denied_when_project_exists_but_actor_cannot_see_it(
        self,
    ):
        class _Conn:
            def close(self):
                pass

        row = _project_row(
            id=37,
            slug="externalwebapp",
            github_repo="example-org/externalwebapp",
        )
        with (
            patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
            patch("yoke_core.domain.db_helpers.query_rows", return_value=[row]),
            patch(
                "yoke_core.domain.handlers.projects_get.actor_visible_project_ids",
                return_value=set(),
            ),
        ):
            outcome = projects_get.handle_projects_resolve_by_github_repo(
                FunctionCallRequest(
                    function="projects.resolve_by_github_repo",
                    actor=ActorContext(actor_id="42", session_id="s-1"),
                    target=TargetRef(kind="global"),
                    payload={"github_repo": "example-org/externalwebapp"},
                ),
            )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "permission_denied")
        self.assertIn("does not have access", outcome.error.message)

    def test_rejects_ambiguous_visible_repo_matches(self):
        class _Conn:
            def close(self):
                pass

        rows = [
            _project_row(
                id=37,
                slug="externalwebapp",
                github_repo="example-org/externalwebapp",
            ),
            _project_row(
                id=38,
                slug="externalwebapp-fork",
                github_repo="Example-Org/ExternalWebapp",
            ),
        ]
        with (
            patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
            patch("yoke_core.domain.db_helpers.query_rows", return_value=rows),
        ):
            outcome = projects_get.handle_projects_resolve_by_github_repo(
                _request(
                    function="projects.resolve_by_github_repo",
                    payload={"github_repo": "example-org/externalwebapp"},
                ),
            )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "ambiguous_project")
        self.assertIn("numeric project id", outcome.error.message)

    def test_returns_only_visible_project_when_duplicate_repo_has_one_grant(
        self,
    ):
        class _Conn:
            def close(self):
                pass

        rows = [
            _project_row(
                id=37,
                slug="externalwebapp",
                github_repo="example-org/externalwebapp",
            ),
            _project_row(
                id=38,
                slug="externalwebapp-hidden",
                github_repo="example-org/externalwebapp",
            ),
        ]
        with (
            patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
            patch("yoke_core.domain.db_helpers.query_rows", return_value=rows),
            patch(
                "yoke_core.domain.handlers.projects_get.actor_visible_project_ids",
                return_value={37},
            ),
        ):
            outcome = projects_get.handle_projects_resolve_by_github_repo(
                FunctionCallRequest(
                    function="projects.resolve_by_github_repo",
                    actor=ActorContext(actor_id="42", session_id="s-1"),
                    target=TargetRef(kind="global"),
                    payload={"github_repo": "example-org/externalwebapp"},
                ),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["row"]["id"], 37)
        self.assertEqual(outcome.result_payload["row"]["slug"], "externalwebapp")


if __name__ == "__main__":
    unittest.main()
