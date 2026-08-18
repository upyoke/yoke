"""Unit tests for deployment flow/run function handlers."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from yoke_core.domain.handlers import deployment_flows


def _assert_flow_connect_restored(testcase: unittest.TestCase) -> None:
    from yoke_core.domain import db_helpers, flow

    testcase.assertIs(flow.connect, db_helpers.connect)


class TestDeploymentFlowHandlers(unittest.TestCase):
    def test_flow_get_returns_field_value(self):
        conn = Mock()
        with patch("yoke_core.domain.flow.cmd_get", return_value="prod"):
            with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
                outcome = deployment_flows.handle_deployment_flow_get(
                    _request(
                        function="deployment_flows.get",
                        payload={
                            "flow_id": "yoke-hosted-prod",
                            "field": "target_environment",
                        },
                    ),
                )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["flow_id"], "yoke-hosted-prod")
        self.assertEqual(
            outcome.result_payload["field"], "target_environment",
        )
        self.assertEqual(outcome.result_payload["value"], "prod")
        conn.close.assert_called_once()
        _assert_flow_connect_restored(self)

    def test_flow_stages_returns_raw_json(self):
        conn = Mock()
        stages = '[{"name":"deploy","kind":"command"}]'
        with patch("yoke_core.domain.flow.cmd_stages", return_value=stages):
            with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
                outcome = deployment_flows.handle_deployment_flow_stages(
                    _request(
                        function="deployment_flows.stages",
                        payload={"flow_id": "yoke-hosted-prod"},
                    ),
                )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["stages"], stages)
        conn.close.assert_called_once()
        _assert_flow_connect_restored(self)

    def test_flow_status_mutation_preserves_the_definition(self):
        conn = Mock()
        with patch("yoke_core.domain.flow.cmd_set_status") as set_status:
            with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
                outcome = deployment_flows.handle_deployment_flow_set_status(
                    _request(
                        function="deployment_flows.set_status",
                        payload={
                            "flow_id": "yoke-hosted-stage",
                            "status": "disabled",
                        },
                    ),
                )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["status"], "disabled")
        set_status.assert_called_once_with(conn, "yoke-hosted-stage", "disabled")
        conn.close.assert_called_once()

    def test_flow_missing_id_returns_payload_error(self):
        outcome = deployment_flows.handle_deployment_flow_get(
            _request(function="deployment_flows.get"),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")


class TestDeploymentHandlerRegistration(unittest.TestCase):
    def test_deployment_function_ids_are_registered(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_registry as registry

        registry.reset_registry_for_tests()
        try:
            register_all_handlers()
            ids = {entry.function_id for entry in registry.list_entries()}
            self.assertIn("deployment_flows.get", ids)
            self.assertIn("deployment_flows.set_status", ids)
            self.assertIn("deployment_flows.stages", ids)
            self.assertIn("deployment_runs.create", ids)
            self.assertIn("deployment_runs.approve", ids)
            self.assertIn("deployment_runs.get", ids)
            self.assertIn("deployment_runs.list", ids)
            self.assertIn("deployment_runs.update", ids)
            self.assertIn("deployment_runs.resolve_target", ids)
            update = registry.lookup("deployment_runs.update")
            self.assertEqual(
                list(update.side_effects),
                ["deployment_runs_update"],
            )
            approve = registry.lookup("deployment_runs.approve")
            self.assertEqual(
                list(approve.side_effects),
                ["deployment_runs_update", "items_deploy_stage_update"],
            )
            flow_status = registry.lookup("deployment_flows.set_status")
            self.assertEqual(
                list(flow_status.side_effects),
                ["deployment_flows_status_update"],
            )
        finally:
            registry.reset_registry_for_tests()


if __name__ == "__main__":
    unittest.main()
