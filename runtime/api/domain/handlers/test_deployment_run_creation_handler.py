"""Creation of a deployment run: lineage, flow status, and who may create.

Creating a run takes no coordination claim: the global create advisory
lock serializes creation and target occupancy serializes deploys, so any
authorized session may create a run.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from yoke_core.domain.deployment_run_create_write import CreatedRun
from yoke_core.domain.handlers import deployment_runs


class TestDeploymentRunCreation(unittest.TestCase):
    def test_run_create_returns_created_run(self):
        created_row = (
            "run-20260616-002|yoke|yoke-hosted-prod|persistent|prod|"
            "||created||2026-06-16T00:00:00Z|||operator"
        )
        with (
            patch(
                "yoke_core.domain.deployment_runs_crud_mutate.create_run",
                return_value=CreatedRun("run-20260616-002", False, None),
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
                        "flow": "yoke-hosted-prod",
                        "release_lineage": "a" * 40,
                        "created_by": "operator",
                    },
                ),
            )
        self.assertTrue(outcome.primary_success)
        cmd_create.assert_called_once_with(
            "yoke",
            "yoke-hosted-prod",
            idempotency_key=None,
            create_request=None,
            environment=None,
            release_lineage="a" * 40,
            created_by="operator",
        )
        self.assertEqual(
            outcome.result_payload["run_id"],
            "run-20260616-002",
        )
        self.assertEqual(outcome.result_payload["flow"], "yoke-hosted-prod")
        self.assertIsNone(outcome.result_payload["release_lineage"])

    def test_run_create_rejects_inactive_flow(self):
        with (
            patch(
                "yoke_core.domain.deployment_runs_crud_mutate.create_run",
                side_effect=ValueError(
                    "deployment flow 'old-flow' is disabled and cannot start new runs"
                ),
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
            "run-old|yoke|yoke-hosted-prod|persistent|prod|"
            + "a" * 40
            + "|failed|release|2026-06-15T00:00:00Z||"
            "2026-06-15T01:00:00Z|operator"
        )
        created = source.replace("run-old", "run-new").replace(
            "|failed|",
            "|created|",
        )
        with (
            patch(
                "yoke_core.domain.deployment_runs_crud_query.cmd_get",
                side_effect=[source, created],
            ),
            patch(
                "yoke_core.domain.deployment_runs_crud_mutate.create_run",
                return_value=CreatedRun("run-new", False, None),
            ) as create,
        ):
            outcome = deployment_runs.handle_deployment_run_create(
                _request(
                    function="deployment_runs.create",
                    payload={
                        "project": "yoke",
                        "flow": "yoke-hosted-prod",
                        "retry_of": "run-old",
                    },
                )
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(create.call_args.kwargs["release_lineage"], "a" * 40)

    def test_run_create_needs_no_coordination_claim(self):
        created_row = (
            "run-20260616-003|platform|platform-prod|persistent|prod|"
            "||created||2026-06-16T00:00:00Z|||operator"
        )
        with (
            patch(
                "yoke_core.domain.deployment_runs_crud_mutate.create_run",
                return_value=CreatedRun("run-20260616-003", False, None),
            ) as cmd_create,
            patch(
                "yoke_core.domain.deployment_runs_crud_query.cmd_get",
                return_value=created_row,
            ),
        ):
            outcome = deployment_runs.handle_deployment_run_create(
                _request(
                    function="deployment_runs.create",
                    payload={"project": "platform", "flow": "platform-prod"},
                ),
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["run_id"], "run-20260616-003")
        cmd_create.assert_called_once()

    def test_run_create_requires_project_and_flow(self):
        outcome = deployment_runs.handle_deployment_run_create(
            _request(
                function="deployment_runs.create",
                payload={"project": "", "flow": "yoke-hosted-prod"},
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")


if __name__ == "__main__":
    unittest.main()
