"""Unit tests for the project_structure.patch.apply handler."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import project_structure as ps_handler
from yoke_core.domain.project_structure import UsageError, ValidationError
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="project_structure.patch.apply",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="project_structure", project_id="yoke"),
        payload=payload or {},
    )


def _command_request(function: str, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="project_structure", project_id="yoke"),
        payload=payload or {},
    )


class TestProjectStructurePatchApply(unittest.TestCase):
    def test_rejects_missing_project_id(self):
        req = _request({"ops": [{"op": "put", "family": "f", "attachment": "a"}]})
        outcome = ps_handler.handle_project_structure_patch_apply(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.project_id")

    def test_rejects_empty_ops(self):
        req = _request({"project_id": "yoke", "ops": []})
        outcome = ps_handler.handle_project_structure_patch_apply(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.ops")

    def test_usage_error_maps_to_payload_invalid(self):
        with patch(
            "yoke_core.domain.project_structure_write.apply_patch",
            side_effect=UsageError("bad op shape"),
        ):
            req = _request(
                {"project_id": "yoke", "ops": [{"op": "put"}]},
            )
            outcome = ps_handler.handle_project_structure_patch_apply(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertIn("bad op shape", outcome.error.message)

    def test_validation_error_maps_to_policy_violation(self):
        with patch(
            "yoke_core.domain.project_structure_write.apply_patch",
            side_effect=ValidationError("payload violates schema"),
        ):
            req = _request(
                {"project_id": "yoke", "ops": [{"op": "put", "family": "x", "attachment": "y", "payload": {}}]},
            )
            outcome = ps_handler.handle_project_structure_patch_apply(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "policy_violation")

    def test_happy_path_returns_applied_ops(self):
        with patch(
            "yoke_core.domain.project_structure_write.apply_patch",
            return_value={
                "project_id": "yoke",
                "applied_ops": [
                    {"op": "put", "family": "cap", "attachment": "v"},
                ],
            },
        ):
            req = _request(
                {
                    "project_id": "yoke",
                    "ops": [{"op": "put", "family": "cap", "attachment": "v", "payload": {}}],
                },
            )
            outcome = ps_handler.handle_project_structure_patch_apply(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["project_id"], "yoke")
        self.assertEqual(len(outcome.result_payload["applied_ops"]), 1)


class TestProjectStructureCommandDefinitionsGet(unittest.TestCase):
    def test_rejects_missing_project_id(self):
        req = _command_request(
            "project_structure.command_definitions.get",
            {"scope": "quick"},
        )
        outcome = ps_handler.handle_project_structure_command_definitions_get(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.project_id")

    def test_rejects_missing_scope(self):
        req = _command_request(
            "project_structure.command_definitions.get",
            {"project_id": "yoke"},
        )
        outcome = ps_handler.handle_project_structure_command_definitions_get(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.scope")

    def test_unknown_scope_maps_to_payload_invalid(self):
        with patch(
            "yoke_core.domain.command_definitions.get_command",
            side_effect=ValueError("Unknown command_definitions scope 'slow'."),
        ):
            req = _command_request(
                "project_structure.command_definitions.get",
                {"project_id": "yoke", "scope": "slow"},
            )
            outcome = ps_handler.handle_project_structure_command_definitions_get(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.scope")

    def test_returns_configured_command(self):
        with patch(
            "yoke_core.domain.command_definitions.get_command",
            return_value="pytest -q",
        ):
            req = _command_request(
                "project_structure.command_definitions.get",
                {"project_id": "yoke", "scope": "quick"},
            )
            outcome = ps_handler.handle_project_structure_command_definitions_get(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["project_id"], "yoke")
        self.assertEqual(outcome.result_payload["scope"], "quick")
        self.assertEqual(outcome.result_payload["command"], "pytest -q")

    def test_absent_command_is_successful_none(self):
        with patch(
            "yoke_core.domain.command_definitions.get_command",
            return_value=None,
        ):
            req = _command_request(
                "project_structure.command_definitions.get",
                {"project_id": "yoke", "scope": "quick"},
            )
            outcome = ps_handler.handle_project_structure_command_definitions_get(req)
        self.assertTrue(outcome.primary_success)
        self.assertIsNone(outcome.result_payload["command"])


class TestProjectStructureCommandDefinitionsList(unittest.TestCase):
    def test_rejects_missing_project_id(self):
        req = _command_request("project_structure.command_definitions.list", {})
        outcome = ps_handler.handle_project_structure_command_definitions_list(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.project_id")

    def test_returns_configured_commands(self):
        commands = {"quick": "pytest -q", "full": "pytest"}
        with patch(
            "yoke_core.domain.command_definitions.list_commands",
            return_value=commands,
        ):
            req = _command_request(
                "project_structure.command_definitions.list",
                {"project_id": "yoke"},
            )
            outcome = ps_handler.handle_project_structure_command_definitions_list(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["project_id"], "yoke")
        self.assertEqual(outcome.result_payload["commands"], commands)


class TestProjectStructureDeployDefaultsGet(unittest.TestCase):
    def test_rejects_missing_project_id(self):
        req = _command_request("project_structure.deploy_defaults.get", {})
        outcome = ps_handler.handle_project_structure_deploy_defaults_get(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.project_id")

    def test_returns_configured_default_flow(self):
        with patch(
            "yoke_core.domain.deploy_defaults.get_default_flow",
            return_value="yoke-hosted-production",
        ):
            req = _command_request(
                "project_structure.deploy_defaults.get",
                {"project_id": "yoke"},
            )
            outcome = ps_handler.handle_project_structure_deploy_defaults_get(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["project_id"], "yoke")
        self.assertEqual(
            outcome.result_payload["deployment_flow"], "yoke-hosted-production"
        )

    def test_absent_default_is_successful_none(self):
        with patch(
            "yoke_core.domain.deploy_defaults.get_default_flow",
            return_value=None,
        ):
            req = _command_request(
                "project_structure.deploy_defaults.get",
                {"project_id": "yoke"},
            )
            outcome = ps_handler.handle_project_structure_deploy_defaults_get(req)
        self.assertTrue(outcome.primary_success)
        self.assertIsNone(outcome.result_payload["deployment_flow"])


if __name__ == "__main__":
    unittest.main()
