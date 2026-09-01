"""Unit tests for the ``projects.list`` handler."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.api.domain.handlers.projects_handler_test_support import (
    project_request as _request,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import projects_get


class TestProjectsList(unittest.TestCase):
    def test_returns_structured_project_rows(self):
        with patch(
            "yoke_core.domain.projects_crud.cmd_list",
            return_value=(
                "1|yoke|Yoke|main|2026-01-01\n"
                "2|externalwebapp|ExternalWebapp|main|2026-01-02"
            ),
        ):
            outcome = projects_get.handle_projects_list(
                _request(function="projects.list"),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            outcome.result_payload["fields"],
            ["id", "slug", "name", "default_branch", "created_at"],
        )
        rows = outcome.result_payload["rows"]
        self.assertEqual(rows[0]["slug"], "yoke")
        self.assertEqual(rows[0]["id"], 1)
        self.assertIsInstance(rows[0]["id"], int)
        self.assertEqual(rows[1]["default_branch"], "main")

    def test_empty_list_returns_no_rows(self):
        with patch("yoke_core.domain.projects_crud.cmd_list", return_value=""):
            outcome = projects_get.handle_projects_list(
                _request(function="projects.list"),
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["rows"], [])

    def test_requested_list_fields_read_from_projects_table(self):
        class _Conn:
            def close(self):
                pass

        with (
            patch(
                "yoke_core.domain.db_helpers.connect",
                return_value=_Conn(),
            ),
            patch(
                "yoke_core.domain.db_helpers.query_rows",
                return_value=[
                    {
                        "id": 37,
                        "slug": "externalwebapp",
                        "github_repo": "example-org/externalwebapp",
                        "public_item_prefix": "EXT",
                    }
                ],
            ) as query_rows,
        ):
            outcome = projects_get.handle_projects_list(
                _request(
                    function="projects.list",
                    payload={
                        "fields": [
                            "id",
                            "slug",
                            "github_repo",
                            "public_item_prefix",
                        ],
                    },
                ),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            outcome.result_payload["fields"],
            ["id", "slug", "github_repo", "public_item_prefix"],
        )
        self.assertEqual(
            outcome.result_payload["rows"],
            [
                {
                    "id": 37,
                    "slug": "externalwebapp",
                    "github_repo": "example-org/externalwebapp",
                    "public_item_prefix": "EXT",
                }
            ],
        )
        query_rows.assert_called_once()
        self.assertIn(
            "SELECT id, slug, github_repo, public_item_prefix FROM projects",
            query_rows.call_args.args[1],
        )

    def test_summary_list_adds_authoritative_project_aggregates(self):
        class _Conn:
            def close(self):
                pass

        base = [
            {
                "id": 37,
                "slug": "externalwebapp",
                "name": "ExternalWebapp",
                "emoji": "◫",
                "github_repo": "example-org/externalwebapp",
                "default_branch": "main",
                "public_item_prefix": "EXT",
            }
        ]
        enriched = [
            {
                **base[0],
                "in_flight_count": 3,
                "ready_count": 2,
                "blocked_count": 1,
                "strategy_doc_count": 4,
                "has_strategy": True,
            }
        ]
        with (
            patch(
                "yoke_core.domain.db_helpers.connect",
                return_value=_Conn(),
            ),
            patch(
                "yoke_core.domain.db_helpers.query_rows",
                return_value=base,
            ),
            patch(
                "yoke_core.domain.project_summary_read.enrich_project_summaries",
                return_value=enriched,
            ) as enrich,
        ):
            outcome = projects_get.handle_projects_list(
                _request(
                    function="projects.list",
                    payload={"include_summary": True},
                ),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["rows"], enriched)
        self.assertIn(
            "in_flight_count",
            outcome.result_payload["fields"],
        )
        enrich.assert_called_once()

    def test_rejects_unknown_requested_list_field(self):
        outcome = projects_get.handle_projects_list(
            _request(
                function="projects.list",
                payload={"fields": ["id", "slug", "not_a_project_column"]},
            ),
        )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_field")
        self.assertIn("not_a_project_column", outcome.error.message)

    def test_numeric_actor_sees_only_granted_projects(self):
        with (
            patch(
                "yoke_core.domain.projects_crud.cmd_list",
                return_value=(
                    "1|yoke|Yoke|main|2026-01-01\n"
                    "2|externalwebapp|ExternalWebapp|main|2026-01-02\n"
                    "3|installer-e2e-test|Installer E2E|main|2026-01-03"
                ),
            ),
            patch(
                "yoke_core.domain.handlers.projects_get.actor_visible_project_ids",
                return_value={2, 3},
            ),
        ):
            outcome = projects_get.handle_projects_list(
                FunctionCallRequest(
                    function="projects.list",
                    actor=ActorContext(actor_id="37", session_id="s-1"),
                    target=TargetRef(kind="global"),
                    payload={},
                ),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            [row["slug"] for row in outcome.result_payload["rows"]],
            ["externalwebapp", "installer-e2e-test"],
        )

    def test_numeric_actor_with_no_grants_sees_no_projects(self):
        with (
            patch(
                "yoke_core.domain.projects_crud.cmd_list",
                return_value="1|yoke|Yoke|main|2026-01-01",
            ),
            patch(
                "yoke_core.domain.handlers.projects_get.actor_visible_project_ids",
                return_value=set(),
            ),
        ):
            outcome = projects_get.handle_projects_list(
                FunctionCallRequest(
                    function="projects.list",
                    actor=ActorContext(actor_id="37", session_id="s-1"),
                    target=TargetRef(kind="global"),
                    payload={},
                ),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["rows"], [])


class TestProjectsListDispatcher(unittest.TestCase):
    def test_direct_dispatch_returns_rows(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_dispatch as _dispatch

        register_all_handlers()
        envelope = {
            "function": "projects.list",
            "actor": {"actor_id": "t", "session_id": ""},
            "target": {"kind": "global"},
            "payload": {},
        }
        with patch(
            "yoke_core.domain.projects_crud.cmd_list",
            return_value="1|yoke|Yoke|main|2026-01-01",
        ):
            response = _dispatch.dispatch(envelope)
        self.assertTrue(
            response.success,
            f"dispatcher rejected projects.list: error={response.error}",
        )
        self.assertEqual(response.result["rows"][0]["slug"], "yoke")


if __name__ == "__main__":
    unittest.main()
