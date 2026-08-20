"""Flow creation is an ordinary command against the flow registry."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers import deployment_flows


STAGES = '[{"name":"merged","step_runner":"auto"}]'


def _create_request(payload: dict, *, project: str | None = "acme"):
    return _request(
        function="deployment_flows.create",
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
    )


class TestDeploymentFlowCreateHandler(unittest.TestCase):
    def test_create_passes_the_declared_target_through(self):
        conn = Mock()
        with patch(
            "yoke_core.domain.flow_create.cmd_create",
            return_value="Created deployment flow: acme-prod",
        ) as create:
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=conn,
            ):
                outcome = deployment_flows.handle_deployment_flow_create(
                    _create_request({
                        "flow_id": "acme-prod",
                        "name": "Acme production",
                        "stages": STAGES,
                        "target_tier": "persistent",
                        "environment": "prod",
                    }),
                )

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["flow_id"], "acme-prod")
        _, kwargs = create.call_args
        self.assertEqual(kwargs["target_tier"], "persistent")
        self.assertEqual(kwargs["environment"], "prod")
        self.assertEqual(kwargs["status"], "active")
        conn.close.assert_called_once()

    def test_create_requires_a_project_target(self):
        outcome = deployment_flows.handle_deployment_flow_create(
            _create_request(
                {"flow_id": "acme-prod", "name": "N", "stages": STAGES},
                project=None,
            ),
        )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_create_rejects_an_empty_stage_document(self):
        outcome = deployment_flows.handle_deployment_flow_create(
            _create_request(
                {"flow_id": "acme-prod", "name": "Acme", "stages": "  "},
            ),
        )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_create_surfaces_an_invalid_flow_as_a_typed_error(self):
        conn = Mock()
        with patch(
            "yoke_core.domain.flow_create.cmd_create",
            side_effect=ValueError("deployment flow 'acme-prod' already exists"),
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=conn,
            ):
                outcome = deployment_flows.handle_deployment_flow_create(
                    _create_request({
                        "flow_id": "acme-prod",
                        "name": "Acme",
                        "stages": STAGES,
                    }),
                )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "flow_invalid")
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
