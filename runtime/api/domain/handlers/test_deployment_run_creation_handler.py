"""Creation of a deployment run: lineage, flow status, and the deploy lock.

Creating a run is gated on the calling session holding the project's
deploy lock, so every test here declares whether it holds one. The two
that are about the gate itself say so in their names; the rest hold it so
the assertion under test is about the run.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from yoke_core.domain.handlers import deployment_runs

#: Where the create handler reads the project deploy lock.
DEPLOY_LOCK = (
    "yoke_core.domain.handlers.deployment_run_creation.deploy_lock_refusal"
)


class TestDeploymentRunCreation(unittest.TestCase):
    def test_run_create_returns_created_run(self):
        created_row = (
            "run-20260616-002|yoke|yoke-hosted-prod|persistent|prod|"
            "||created||2026-06-16T00:00:00Z|||operator"
        )
        with (
            patch(DEPLOY_LOCK, return_value=None),
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
            patch(DEPLOY_LOCK, return_value=None),
            patch(
                "yoke_core.domain.deployment_runs_crud_mutate.cmd_create_run",
                side_effect=ValueError(
                    "deployment flow 'old-flow' is disabled and cannot start "
                    "new runs"
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
            patch(DEPLOY_LOCK, return_value=None),
            patch(
                "yoke_core.domain.deployment_runs_crud_query.cmd_get",
                side_effect=[source, created],
            ),
            patch(
                "yoke_core.domain.deployment_runs_crud_mutate.cmd_create_run",
                return_value="run-new",
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

    def test_run_create_refuses_without_the_project_deploy_lock(self):
        refusal = (
            "deployment_runs.create refused: no session holds the deploy "
            "lock DEPLOY:yoke for project 'yoke'."
        )
        with (
            patch(DEPLOY_LOCK, return_value=refusal) as lock,
            patch(
                "yoke_core.domain.deployment_runs_crud_mutate.cmd_create_run",
            ) as cmd_create,
        ):
            outcome = deployment_runs.handle_deployment_run_create(
                _request(
                    function="deployment_runs.create",
                    payload={"project": "yoke", "flow": "yoke-hosted-prod"},
                ),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "deploy_lock_required")
        self.assertIn("DEPLOY:yoke", outcome.error.message)
        cmd_create.assert_not_called()
        self.assertEqual(lock.call_args.args[0], "yoke")
        self.assertEqual(
            lock.call_args.kwargs["operation"], "deployment_runs.create",
        )

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
