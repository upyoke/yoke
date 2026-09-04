"""Unit tests for deployment-run function handlers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers import deployment_runs


class TestDeploymentRunHandlers(unittest.TestCase):
    def _run_target(self) -> TargetRef:
        return TargetRef(
            kind="workflow_run",
            workflow_run_id="run-20260616-001",
        )

    def test_run_get_returns_pipe_row_as_dict(self):
        from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

        values = [
            "run-20260616-001",
            "yoke",
            "yoke-hosted-prod",
            "persistent",
            "prod",
            "",
            "created",
            "",
            "2026-06-16T00:00:00Z",
            "",
            "",
            "operator",
            '{"schema":1,"items":[],"commits":[]}',
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
            outcome.result_payload["run"]["target_environment"],
            "prod",
        )
        self.assertEqual(
            outcome.result_payload["run"]["carried_work"]["schema"],
            1,
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
        rows = [
            {
                "id": "run-20260616-001",
                "project": "yoke",
                "flow": "flow",
                "target_tier": "persistent",
                "target_environment": "prod",
                "status": "created",
                "member_items": [],
                "stages": [],
                "stage_index": -1,
                "stage_count": 0,
                "waiting_on_approval": False,
            }
        ]
        with patch(
            "yoke_core.domain.deployment_run_list_read.list_deployment_runs",
            return_value=rows,
        ) as list_runs:
            outcome = deployment_runs.handle_deployment_run_list(
                _request(
                    function="deployment_runs.list",
                    payload={
                        "project": "yoke",
                        "status": "created",
                        "limit": 7,
                    },
                ),
            )
        self.assertTrue(outcome.primary_success)
        list_runs.assert_called_once_with(
            project="yoke",
            status="created",
            limit=7,
        )
        self.assertEqual(outcome.result_payload["rows"][0]["project"], "yoke")
        self.assertEqual(outcome.result_payload["limit"], 7)

    def test_run_list_defaults_to_bounded_recent_history(self):
        with patch(
            "yoke_core.domain.deployment_run_list_read.list_deployment_runs",
            return_value=[],
        ) as list_runs:
            outcome = deployment_runs.handle_deployment_run_list(
                _request(function="deployment_runs.list", payload={}),
            )

        self.assertTrue(outcome.primary_success)
        list_runs.assert_called_once_with(
            project=None,
            status=None,
            limit=20,
        )
        self.assertEqual(outcome.result_payload["limit"], 20)

    def test_run_list_rejects_invalid_limit(self):
        outcome = deployment_runs.handle_deployment_run_list(
            _request(
                function="deployment_runs.list",
                payload={"limit": 1001},
            ),
        )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertEqual(outcome.error.jsonpath, "$.payload.limit")

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
            "run-20260616-001",
            "status",
            "succeeded",
            force=True,
        )
        self.assertTrue(outcome.result_payload["updated"])

    def test_run_approve_advances_exact_workflow_run(self):
        from yoke_core.domain.deployment_run_approval import RunApproval

        approval = RunApproval(
            run_id="run-20260616-001",
            project="yoke",
            approved_stage="prod-approval",
            next_stage="prod",
            approved_at="2026-06-16T01:02:03Z",
            member_item_ids=(19, 20),
        )
        with (
            patch(
                "yoke_core.domain.deployment_run_approval.approve_run",
                return_value=approval,
            ) as approve,
            patch(
                "yoke_core.domain.deployment_run_approval.emit_run_approval",
                return_value="event-1",
            ) as emit,
        ):
            outcome = deployment_runs.handle_deployment_run_approve(
                _request(
                    function="deployment_runs.approve",
                    target=self._run_target(),
                    payload={"note": "stage verified"},
                    actor_id="7",
                ),
            )

        self.assertTrue(outcome.primary_success)
        approve.assert_called_once_with(
            "run-20260616-001",
            actor_id=7,
            session_id="s-1",
            note="stage verified",
        )
        emit.assert_called_once()
        self.assertEqual(outcome.result_payload["next_stage"], "prod")
        self.assertEqual(outcome.result_payload["member_item_ids"], [19, 20])
        self.assertEqual(outcome.result_payload["event_id"], "event-1")

    def test_resolve_target_returns_typed_triple(self):
        with patch(
            "yoke_core.domain.deployment_run_target_resolution.cmd_resolve_target",
            return_value=("persistent", 201, "prod"),
        ):
            outcome = deployment_runs.handle_deployment_run_resolve_target(
                _request(
                    function="deployment_runs.resolve_target",
                    payload={
                        "project": "yoke",
                        "flow": "yoke-hosted-prod",
                    },
                ),
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["target_tier"], "persistent")
        self.assertEqual(outcome.result_payload["target_environment"], "prod")


if __name__ == "__main__":
    unittest.main()
