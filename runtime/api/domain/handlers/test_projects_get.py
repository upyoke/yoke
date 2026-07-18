"""Unit tests for the ``projects.get`` handler."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import projects_get
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(payload=None, function: str = "projects.get") -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


class TestProjectsGet(unittest.TestCase):
    def test_rejects_missing_project(self):
        outcome = projects_get.handle_projects_get(_request({}))
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertIn("project", outcome.error.message)

    def test_rejects_non_string_field(self):
        outcome = projects_get.handle_projects_get(
            _request({"project": "yoke", "field": 42}),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_returns_field_value_for_known_project_and_field(self):
        with patch(
            "yoke_core.domain.projects_crud.cmd_get",
            return_value="main",
        ):
            outcome = projects_get.handle_projects_get(
                _request({"project": "yoke", "field": "default_branch"}),
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["project"], "yoke")
        self.assertEqual(outcome.result_payload["field"], "default_branch")
        self.assertEqual(outcome.result_payload["value"], "main")
        self.assertNotIn("row", outcome.result_payload)

    def test_returns_full_row_when_field_absent(self):
        from yoke_core.domain.projects import PROJECT_FIELDS

        # Build a pipe-delimited row that matches PROJECT_FIELDS order.
        values = [
            "1", "yoke", "Yoke", "", "main", "owner/yoke", "YOK",
            "2026-01-01",
        ]
        # Pad / trim to the live PROJECT_FIELDS length so the test does not break
        # when a new column lands without updating the fixture.
        while len(values) < len(PROJECT_FIELDS):
            values.append("")
        values = values[: len(PROJECT_FIELDS)]
        raw = "|".join(values)
        with patch(
            "yoke_core.domain.projects_crud.cmd_get",
            return_value=raw,
        ):
            outcome = projects_get.handle_projects_get(
                _request({"project": "yoke"}),
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["project"], "yoke")
        row = outcome.result_payload["row"]
        self.assertIsInstance(row, dict)
        # Every PROJECT_FIELDS column present in the response row.
        self.assertEqual(set(row.keys()), set(PROJECT_FIELDS))
        # Empty pipe segments surface as None for honest typing.
        self.assertIsNone(row["emoji"])

    def test_unknown_project_returns_not_found(self):
        with patch(
            "yoke_core.domain.projects_crud.cmd_get",
            return_value=None,
        ):
            outcome = projects_get.handle_projects_get(
                _request({"project": "ghost"}),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")
        self.assertIn("ghost", outcome.error.message)

    def test_lookup_error_project_returns_not_found(self):
        with patch(
            "yoke_core.domain.projects_crud.cmd_get",
            side_effect=LookupError("project 'ghost' not found"),
        ):
            outcome = projects_get.handle_projects_get(
                _request({"project": "ghost"}),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")
        self.assertIn("ghost", outcome.error.message)

    def test_unknown_field_returns_invalid_field(self):
        with patch(
            "yoke_core.domain.projects_crud.cmd_get",
            side_effect=ValueError("unknown field"),
        ):
            outcome = projects_get.handle_projects_get(
                _request({"project": "yoke", "field": "definitely_not_a_column"}),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_field")
        # Valid-fields list named in the error message.
        from yoke_core.domain.projects import PROJECT_FIELDS

        for name in PROJECT_FIELDS:
            self.assertIn(name, outcome.error.message)


class TestProjectsGetAdapterRegistration(unittest.TestCase):
    """AC-47 — projects.get is registered and appears in the adapter inventory."""

    def test_function_id_registered(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_registry as _reg

        register_all_handlers()
        entry = _reg.lookup("projects.get")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.owner_module, "yoke_core.domain.handlers.projects_get")
        self.assertEqual(list(entry.target_kinds), ["global"])
        self.assertIsNone(entry.claim_required_kind)

    def test_adapter_entry_present(self):
        from yoke_core.api.service_client_structured_api_adapter_inventory import (
            adapter_index,
        )

        index = adapter_index()
        self.assertIn("projects.get", index)
        entry = index["projects.get"]
        self.assertIn("projects get", entry.cli_invocation)
        self.assertTrue(entry.read_shape)


class TestProjectsGetDispatcher(unittest.TestCase):
    """AC-48 — direct dispatcher call returns the field value without a work claim."""

    def test_direct_dispatch_returns_field_value(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_dispatch as _dispatch

        register_all_handlers()
        envelope = {
            "function": "projects.get",
            "actor": {"actor_id": "t", "session_id": ""},
            "target": {"kind": "global"},
            "payload": {"project": "yoke", "field": "default_branch"},
        }
        with patch(
            "yoke_core.domain.projects_crud.cmd_get",
            return_value="main",
        ):
            response = _dispatch.dispatch(envelope)
        self.assertTrue(
            response.success,
            f"dispatcher rejected projects.get: error={response.error}",
        )
        self.assertEqual(response.result["value"], "main")
        self.assertEqual(response.result["field"], "default_branch")


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
            [
                "id", "slug", "name", "default_branch", "created_at",
            ],
        )
        rows = outcome.result_payload["rows"]
        self.assertEqual(rows[0]["slug"], "yoke")
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
                return_value=[{
                    "id": 37,
                    "slug": "externalwebapp",
                    "github_repo": "example-org/externalwebapp",
                    "public_item_prefix": "EXT",
                }],
            ) as query_rows,
        ):
            outcome = projects_get.handle_projects_list(
                _request(
                    function="projects.list",
                    payload={
                        "fields": [
                            "id", "slug", "github_repo", "public_item_prefix",
                        ],
                    },
                ),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            outcome.result_payload["fields"],
            ["id", "slug", "github_repo", "public_item_prefix"],
        )
        self.assertEqual(outcome.result_payload["rows"], [{
            "id": 37,
            "slug": "externalwebapp",
            "github_repo": "example-org/externalwebapp",
            "public_item_prefix": "EXT",
        }])
        query_rows.assert_called_once()
        self.assertIn(
            "SELECT id, slug, github_repo, public_item_prefix FROM projects",
            query_rows.call_args.args[1],
        )

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


class TestProjectsResolveByGithubRepo(unittest.TestCase):
    def test_returns_visible_project_for_matching_repo(self):
        class _Conn:
            def close(self):
                pass

        row = _project_row(id=37, slug="externalwebapp", github_repo="example-org/externalwebapp")
        with (
            patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
            patch("yoke_core.domain.db_helpers.query_rows", return_value=[row]),
        ):
            outcome = projects_get.handle_projects_resolve_by_github_repo(
                _request(
                    function="projects.resolve_by_github_repo",
                    payload={"github_repo": "git@github.com:Example-Org/ExternalWebapp.git"},
                ),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["github_repo"], "example-org/externalwebapp")
        self.assertEqual(outcome.result_payload["row"]["id"], 37)
        self.assertEqual(outcome.result_payload["row"]["slug"], "externalwebapp")

    def test_returns_not_found_when_no_project_has_repo(self):
        class _Conn:
            def close(self):
                pass

        row = _project_row(id=37, slug="externalwebapp", github_repo="example-org/externalwebapp")
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

    def test_returns_permission_denied_when_project_exists_but_actor_cannot_see_it(self):
        class _Conn:
            def close(self):
                pass

        row = _project_row(id=37, slug="externalwebapp", github_repo="example-org/externalwebapp")
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
            _project_row(id=37, slug="externalwebapp", github_repo="example-org/externalwebapp"),
            _project_row(id=38, slug="externalwebapp-fork", github_repo="Example-Org/ExternalWebapp"),
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

    def test_returns_only_visible_project_when_duplicate_repo_has_one_grant(self):
        class _Conn:
            def close(self):
                pass

        rows = [
            _project_row(id=37, slug="externalwebapp", github_repo="example-org/externalwebapp"),
            _project_row(id=38, slug="externalwebapp-hidden", github_repo="example-org/externalwebapp"),
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


def _project_row(**overrides):
    row = {
        "id": 1,
        "slug": "demo",
        "name": "Demo",
        "emoji": None,
        "default_branch": "main",
        "github_repo": "owner/demo",
        "public_item_prefix": "DMO",
        "github_sync_mode": None,
        "created_at": "2026-01-01",
    }
    row.update(overrides)
    return row


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
