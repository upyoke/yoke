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
                            "flow_id": "yoke-hosted-production",
                            "field": "target_env",
                        },
                    ),
                )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            outcome.result_payload["flow_id"], "yoke-hosted-production"
        )
        self.assertEqual(outcome.result_payload["field"], "target_env")
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
                        payload={"flow_id": "yoke-hosted-production"},
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
        set_status.assert_called_once_with(
            conn, "yoke-hosted-stage", "disabled"
        )
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
            "run-20260616-001", "yoke", "yoke-hosted-production", "production",
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
        self.assertEqual(
            outcome.result_payload["run"]["target_env"], "production"
        )

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

    def test_run_approve_advances_exact_workflow_run(self):
        from yoke_core.domain.deployment_run_approval import RunApproval

        approval = RunApproval(
            run_id="run-20260616-001",
            project="yoke",
            approved_stage="production-approval",
            next_stage="production",
            approved_at="2026-06-16T01:02:03Z",
            member_item_ids=(19, 20),
        )
        with patch(
            "yoke_core.domain.deployment_run_approval.approve_run",
            return_value=approval,
        ) as approve, patch(
            "yoke_core.domain.deployment_run_approval.emit_run_approval",
            return_value="event-1",
        ) as emit:
            outcome = deployment_runs.handle_deployment_run_approve(
                _request(
                    function="deployment_runs.approve",
                    target=self._run_target(),
                    payload={"note": "stage verified"},
                ),
            )

        self.assertTrue(outcome.primary_success)
        approve.assert_called_once_with("run-20260616-001")
        emit.assert_called_once()
        self.assertEqual(outcome.result_payload["next_stage"], "production")
        self.assertEqual(outcome.result_payload["member_item_ids"], [19, 20])
        self.assertEqual(outcome.result_payload["event_id"], "event-1")

    def test_run_create_returns_created_run(self):
        created_row = (
            "run-20260616-002|yoke|yoke-hosted-production|production|"
            "||created||2026-06-16T00:00:00Z|||operator"
        )
        with patch(
            "yoke_core.domain.deployment_runs_crud_mutate.cmd_create_run",
            return_value="run-20260616-002",
        ) as cmd_create, patch(
            "yoke_core.domain.deployment_runs_crud_query.cmd_get",
            return_value=created_row,
        ):
            outcome = deployment_runs.handle_deployment_run_create(
                _request(
                    function="deployment_runs.create",
                    payload={
                        "project": "yoke",
                        "flow": "yoke-hosted-production",
                        "created_by": "operator",
                    },
                ),
            )
        self.assertTrue(outcome.primary_success)
        cmd_create.assert_called_once_with(
            "yoke", "yoke-hosted-production",
            target_env=None, created_by="operator",
        )
        self.assertEqual(
            outcome.result_payload["run_id"], "run-20260616-002",
        )
        self.assertEqual(outcome.result_payload["flow"], "yoke-hosted-production")

    def test_run_create_rejects_inactive_flow(self):
        with patch(
            "yoke_core.domain.deployment_runs_crud_mutate.cmd_create_run",
            side_effect=ValueError(
                "deployment flow 'old-flow' is disabled and cannot start "
                "new runs"
            ),
        ):
            outcome = deployment_runs.handle_deployment_run_create(
                _request(
                    function="deployment_runs.create",
                    payload={"project": "yoke", "flow": "old-flow"},
                ),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "run_create_rejected")

    def test_run_create_requires_project_and_flow(self):
        outcome = deployment_runs.handle_deployment_run_create(
            _request(
                function="deployment_runs.create",
                payload={"project": "", "flow": "yoke-hosted-production"},
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

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
                        "flow": "yoke-hosted-production",
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
            self.assertIn("deployment_flows.set_status", ids)
            self.assertIn("deployment_flows.stages", ids)
            self.assertIn("deployment_runs.create", ids)
            self.assertIn("deployment_runs.approve", ids)
            self.assertIn("deployment_runs.get", ids)
            self.assertIn("deployment_runs.list", ids)
            self.assertIn("deployment_runs.update", ids)
            self.assertIn("deployment_runs.resolve_target_env", ids)
            update = registry.lookup("deployment_runs.update")
            self.assertEqual(
                list(update.side_effects), ["deployment_runs_update"],
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
