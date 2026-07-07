"""Unit tests for deployment flow/run function handlers."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from yoke_core.domain.handlers import deployment_flows, deployment_runs
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(
    *,
    function: str,
    target: TargetRef | None = None,
    payload: dict | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target or TargetRef(kind="global"),
        payload=payload or {},
    )


class TestDeploymentFlowHandlers(unittest.TestCase):
    def test_flow_get_returns_field_value(self):
        conn = Mock()
        with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
            with patch("yoke_core.domain.flow.cmd_get", return_value="prod"):
                outcome = deployment_flows.handle_deployment_flow_get(
                    _request(
                        function="deployment_flows.get",
                        payload={
                            "flow_id": "yoke-prod-release",
                            "field": "target_env",
                        },
                    ),
                )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["flow_id"], "yoke-prod-release")
        self.assertEqual(outcome.result_payload["field"], "target_env")
        self.assertEqual(outcome.result_payload["value"], "prod")
        conn.close.assert_called_once()

    def test_flow_stages_returns_raw_json(self):
        conn = Mock()
        stages = '[{"name":"deploy","kind":"command"}]'
        with patch("yoke_core.domain.db_helpers.connect", return_value=conn):
            with patch("yoke_core.domain.flow.cmd_stages", return_value=stages):
                outcome = deployment_flows.handle_deployment_flow_stages(
                    _request(
                        function="deployment_flows.stages",
                        payload={"flow_id": "yoke-prod-release"},
                    ),
                )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["stages"], stages)
        conn.close.assert_called_once()

    def test_flow_missing_id_returns_payload_error(self):
        outcome = deployment_flows.handle_deployment_flow_get(
            _request(function="deployment_flows.get"),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")


class TestDeploymentRunHandlers(unittest.TestCase):
    def _run_target(self) -> TargetRef:
        return TargetRef(
            kind="workflow_run",
            workflow_run_id="run-20260616-001",
        )

    def test_run_get_returns_pipe_row_as_dict(self):
        from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

        values = [
            "run-20260616-001", "yoke", "yoke-prod-release", "prod",
            "", "created", "", "2026-06-16T00:00:00Z", "", "", "operator",
        ]
        raw = "|".join(values[: len(RUN_FIELDS)])
        with patch(
            "yoke_core.domain.deployment_runs_crud_query.cmd_get",
            return_value=raw,
        ):
            outcome = deployment_runs.handle_deployment_run_get(
                _request(
                    function="deployment_runs.get",
                    target=self._run_target(),
                ),
            )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["run"]["id"], "run-20260616-001")
        self.assertEqual(outcome.result_payload["run"]["target_env"], "prod")

    def test_run_get_not_found_returns_not_found(self):
        with patch(
            "yoke_core.domain.deployment_runs_crud_query.cmd_get",
            return_value=None,
        ):
            outcome = deployment_runs.handle_deployment_run_get(
                _request(
                    function="deployment_runs.get",
                    target=self._run_target(),
                ),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")

    def test_run_list_uses_project_and_status_filters(self):
        raw = "run-20260616-001|yoke|flow|prod||created||now|||operator"
        with patch(
            "yoke_core.domain.deployment_runs_crud_query.cmd_list",
            return_value=raw,
        ) as cmd_list:
            outcome = deployment_runs.handle_deployment_run_list(
                _request(
                    function="deployment_runs.list",
                    payload={"project": "yoke", "status": "created"},
                ),
            )
        self.assertTrue(outcome.primary_success)
        cmd_list.assert_called_once_with(project="yoke", status="created")
        self.assertEqual(outcome.result_payload["rows"][0]["project"], "yoke")

    def test_run_update_maps_invalid_field(self):
        with patch(
            "yoke_core.domain.deployment_runs_crud_mutate.cmd_update",
            return_value="Error: field 'flow' is not updatable",
        ):
            outcome = deployment_runs.handle_deployment_run_update(
                _request(
                    function="deployment_runs.update",
                    target=self._run_target(),
                    payload={"field": "flow", "value": "other"},
                ),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_field")

    def test_run_update_success(self):
        with patch(
            "yoke_core.domain.deployment_runs_crud_mutate.cmd_update",
            return_value=None,
        ) as cmd_update:
            outcome = deployment_runs.handle_deployment_run_update(
                _request(
                    function="deployment_runs.update",
                    target=self._run_target(),
                    payload={
                        "field": "status",
                        "value": "succeeded",
                        "force": True,
                    },
                ),
            )
        self.assertTrue(outcome.primary_success)
        cmd_update.assert_called_once_with(
            "run-20260616-001", "status", "succeeded", force=True,
        )
        self.assertTrue(outcome.result_payload["updated"])

    def test_resolve_target_env_returns_raw_value(self):
        with patch(
            "yoke_core.domain.deployment_runs_preview.cmd_resolve_target_env",
            return_value="prod",
        ):
            outcome = deployment_runs.handle_deployment_run_resolve_target_env(
                _request(
                    function="deployment_runs.resolve_target_env",
                    payload={
                        "project": "yoke",
                        "flow": "yoke-prod-release",
                    },
                ),
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["target_env"], "prod")


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
            self.assertIn("deployment_flows.stages", ids)
            self.assertIn("deployment_runs.get", ids)
            self.assertIn("deployment_runs.list", ids)
            self.assertIn("deployment_runs.update", ids)
            self.assertIn("deployment_runs.resolve_target_env", ids)
            update = registry.lookup("deployment_runs.update")
            self.assertEqual(
                list(update.side_effects), ["deployment_runs_update"],
            )
        finally:
            registry.reset_registry_for_tests()


if __name__ == "__main__":
    unittest.main()
