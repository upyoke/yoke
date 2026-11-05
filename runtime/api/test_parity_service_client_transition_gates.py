"""Parity tests — status transitions and mutation-layer gates."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


from runtime.api.service_client_in_process_test_support import (
    run_parity_client as _run_service_client,
)
from runtime.api.parity_service_client_test_helpers import (
    make_write_parity_env,
)


@pytest.fixture()
def write_parity_env():
    with make_write_parity_env() as env:
        yield env


class TestTransitionParity:
    """Verify forward and exceptional transitions in the domain layer."""

    def test_forward_transitions_accepted(self):
        """Forward transitions follow the epic workflow."""
        workflow = builtin_workflow_runtime('epic')
        forward_cases = [('idea', 'refining-idea'), ('refining-idea', 'refined-idea'), ('refined-idea', 'planning'), ('planning', 'planned'), ('implementing', 'reviewing-implementation'), ('reviewing-implementation', 'reviewed-implementation'), ('reviewed-implementation', 'polishing-implementation'), ('polishing-implementation', 'implemented'), ('implemented', 'release'), ('release', 'done')]
        for from_s, to_s in forward_cases:
            assert workflow.is_forward_transition(from_s, to_s), f'Domain should accept {from_s} -> {to_s}'

    def test_backward_transitions_rejected(self):
        """Backward transitions are rejected by the epic workflow."""
        workflow = builtin_workflow_runtime('epic')
        backward_cases = [('done', 'planning'), ('planned', 'idea'), ('release', 'implementing')]
        for from_s, to_s in backward_cases:
            assert not workflow.is_forward_transition(from_s, to_s), f'Domain should reject {from_s} -> {to_s}'

    def test_exceptional_transitions_not_forward(self):
        """Transitions involving exceptional statuses are not forward moves."""
        workflow = builtin_workflow_runtime('epic')
        cases = [('planning', 'blocked'), ('blocked', 'planning')]
        for from_s, to_s in cases:
            assert not workflow.is_forward_transition(from_s, to_s)

    def test_issue_workflow_parity(self):
        """Issue transitions follow the built-in workflow runtime."""
        workflow = builtin_workflow_runtime('issue')
        assert not workflow.is_forward_transition('refined-idea', 'planning')
        assert workflow.is_forward_transition('refined-idea', 'implementing')

    def test_epic_workflow_parity(self):
        """Epic transitions follow the built-in workflow runtime."""
        workflow = builtin_workflow_runtime('epic')
        assert workflow.is_forward_transition('refined-idea', 'planning')


class TestGateParity:
    """Verify that gates enforced by the mutation layer produce consistent
    rejections across both API and service-client surfaces."""

    def test_done_without_nonce_rejected_both(self, write_parity_env):
        """Both surfaces should reject setting status=done without the
        done-ceremony nonce (unless force is set)."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # API — item 1 is implementing, try to set done without nonce
        api_resp = client.patch("/v1/items/YOK-1", json={"status": "done"})
        assert api_resp.status_code == 409

        # CLI
        cli_result = _run_service_client(
            db_path,
            "update-item",
            "YOK-1",
            "--field",
            "status",
            "--value",
            "done",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False
        assert "GATE_DONE_NONCE" in cli_data.get("error_code", "")
