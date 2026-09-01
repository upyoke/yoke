"""Unit tests for the ``projects.get`` handler."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.api.domain.handlers.projects_handler_test_support import (
    project_request as _request,
)
from yoke_core.domain.handlers import projects_get
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
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

    def test_id_field_value_is_numeric(self):
        with patch(
            "yoke_core.domain.projects_crud.cmd_get",
            return_value="1",
        ):
            outcome = projects_get.handle_projects_get(
                _request({"project": "yoke", "field": "id"}),
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["value"], 1)
        self.assertIsInstance(outcome.result_payload["value"], int)

    def test_returns_full_row_when_field_absent(self):
        from yoke_core.domain.projects import PROJECT_FIELDS

        # Build a pipe-delimited row that matches PROJECT_FIELDS order.
        values = [
            "1",
            "yoke",
            "Yoke",
            "",
            "main",
            "owner/yoke",
            "YOK",
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
        self.assertEqual(row["id"], 1)
        self.assertIsInstance(row["id"], int)
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

    def test_authenticated_actor_reads_only_visible_project(self):
        class _Connection:
            def close(self):
                pass

        request = FunctionCallRequest(
            function="projects.get",
            actor=ActorContext(actor_id="17", session_id="s-1"),
            target=TargetRef(kind="global"),
            payload={"project": "platform", "field": "id"},
        )
        identity = type("Identity", (), {"id": 3})()
        with (
            patch(
                "yoke_core.domain.db_helpers.connect",
                return_value=_Connection(),
            ),
            patch(
                "yoke_core.domain.handlers.projects_get.actor_visible_project_ids",
                return_value={3},
            ) as visible,
            patch(
                "yoke_core.domain.project_identity.resolve_project",
                return_value=identity,
            ) as resolve,
            patch(
                "yoke_core.domain.projects_crud.cmd_get",
                return_value="3",
            ) as get,
        ):
            outcome = projects_get.handle_projects_get(request)

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["value"], 3)
        self.assertIsInstance(outcome.result_payload["value"], int)
        visible.assert_called_once()
        self.assertEqual(resolve.call_args.kwargs["visible_project_ids"], {3})
        get.assert_called_once_with("3", field="id")

    def test_authenticated_actor_cannot_read_invisible_project(self):
        class _Connection:
            def close(self):
                pass

        request = FunctionCallRequest(
            function="projects.get",
            actor=ActorContext(actor_id="17", session_id="s-1"),
            target=TargetRef(kind="global"),
            payload={"project": "other"},
        )
        with (
            patch(
                "yoke_core.domain.db_helpers.connect",
                return_value=_Connection(),
            ),
            patch(
                "yoke_core.domain.handlers.projects_get.actor_visible_project_ids",
                return_value={3},
            ),
            patch(
                "yoke_core.domain.project_identity.resolve_project",
                return_value=None,
            ),
            patch("yoke_core.domain.projects_crud.cmd_get") as get,
        ):
            outcome = projects_get.handle_projects_get(request)

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")
        get.assert_not_called()


class TestProjectsGetAdapterRegistration(unittest.TestCase):
    """Projects.get is registered and appears in the adapter inventory."""

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
    """Direct dispatcher call returns the field value without a work claim."""

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


if __name__ == "__main__":
    unittest.main()
