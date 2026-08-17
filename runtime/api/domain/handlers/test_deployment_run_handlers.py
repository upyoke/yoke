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
            "yoke-hosted-production",
            "persistent",
            "production",
            "",
            "created",
            "",
            "2026-06-16T00:00:00Z",
            "",
            "",
            "operator",
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
            outcome.result_payload["run"]["target_environment_id"],
            "production",
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
                "target_environment_id": "production",
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
            approved_stage="production-approval",
            next_stage="production",
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
        self.assertEqual(outcome.result_payload["next_stage"], "production")
        self.assertEqual(outcome.result_payload["member_item_ids"], [19, 20])
        self.assertEqual(outcome.result_payload["event_id"], "event-1")

    def test_run_create_returns_created_run(self):
        created_row = (
            "run-20260616-002|yoke|yoke-hosted-production|production|"
            "||created||2026-06-16T00:00:00Z|||operator"
        )
        with (
            patch(
                "yoke_core.domain.deployment_runs_crud_mutate.cmd_create_run",
                return_value="run-20260616-002",
            ) as cmd_create,
            patch(
                "yoke_core.domain.deployment_runs_crud_query.cmd_get",
                return_value=created_row,
            ),
        ):
            outcome = deployment_runs.handle_deployment_run_create(
                _request(
                    function="deployment_runs.create",
                    payload={
                        "project": "yoke",
                        "flow": "yoke-hosted-production",
                        "release_lineage": "a" * 40,
                        "created_by": "operator",
                    },
                ),
            )
        self.assertTrue(outcome.primary_success)
        cmd_create.assert_called_once_with(
            "yoke",
            "yoke-hosted-production",
            environment=None,
            release_lineage="a" * 40,
            created_by="operator",
        )
        self.assertEqual(
            outcome.result_payload["run_id"],
            "run-20260616-002",
        )
        self.assertEqual(outcome.result_payload["flow"], "yoke-hosted-production")
        self.assertIsNone(outcome.result_payload["release_lineage"])

    def test_run_create_rejects_inactive_flow(self):
        with patch(
            "yoke_core.domain.deployment_runs_crud_mutate.cmd_create_run",
            side_effect=ValueError(
                "deployment flow 'old-flow' is disabled and cannot start new runs"
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

    def test_run_create_reuses_the_retry_source_lineage(self):
        source = (
            "run-old|yoke|yoke-hosted-production|persistent|production|"
            + "a" * 40
            + "|failed|release|2026-06-15T00:00:00Z||"
            "2026-06-15T01:00:00Z|operator"
        )
        created = source.replace("run-old", "run-new").replace(
            "|failed|", "|created|",
        )
        with (
            patch(
                "yoke_core.domain.deployment_runs_crud_query.cmd_get",
                side_effect=[source, created],
            ),
            patch(
                "yoke_core.domain.deployment_runs_crud_mutate.cmd_create_run",
                return_value="run-new",
            ) as create,
        ):
            outcome = deployment_runs.handle_deployment_run_create(_request(
                function="deployment_runs.create",
                payload={
                    "project": "yoke", "flow": "yoke-hosted-production",
                    "retry_of": "run-old",
                },
            ))
        self.assertTrue(outcome.primary_success)
        self.assertEqual(create.call_args.kwargs["release_lineage"], "a" * 40)

    def test_run_create_requires_project_and_flow(self):
        outcome = deployment_runs.handle_deployment_run_create(
            _request(
                function="deployment_runs.create",
                payload={"project": "", "flow": "yoke-hosted-production"},
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_resolve_target_returns_typed_triple(self):
        with patch(
            "yoke_core.domain.deployment_run_target_resolution."
            "cmd_resolve_target",
            return_value=("persistent", "production", "prod"),
        ):
            outcome = deployment_runs.handle_deployment_run_resolve_target(
                _request(
                    function="deployment_runs.resolve_target",
                    payload={
                        "project": "yoke",
                        "flow": "yoke-hosted-production",
                    },
                ),
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["target_tier"], "persistent")
        self.assertEqual(
            outcome.result_payload["target_environment_id"], "production",
        )
        self.assertEqual(
            outcome.result_payload["target_environment_name"], "prod",
        )


if __name__ == "__main__":
    unittest.main()
