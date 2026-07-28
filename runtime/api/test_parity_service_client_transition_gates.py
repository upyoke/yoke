"""Parity tests — status transitions and mutation-layer gates."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

# ``_run_service_client`` is the (backend-agnostic) subprocess helper; it copies
# os.environ at call time, so it inherits the per-test ``YOKE_PG_DSN`` repointed
# by the parity-env builders below.
from runtime.api.test_parity import _run_service_client
from runtime.api.parity_service_client_test_helpers import (
    make_read_parity_env,
    make_write_parity_env,
)


@pytest.fixture()
def parity_env():
    # Backend-aware read-parity env using one per-test Postgres database.
    with make_read_parity_env() as env:
        yield env


@pytest.fixture()
def write_parity_env():
    with make_write_parity_env() as env:
        yield env


# ===========================================================================
# Group 4: Status validation and transition checks
# ===========================================================================


class TestTransitionParity:
    """Verify CLI validate-transition matches domain layer."""

    def test_forward_transitions_accepted(self, parity_env):
        """Forward transitions should be accepted by both surfaces."""
        db_path = parity_env["db_path"]
        workflow = builtin_workflow_runtime("epic")

        forward_cases = [
            ("idea", "refining-idea"),
            ("refining-idea", "refined-idea"),
            ("refined-idea", "planning"),
            ("planning", "planned"),
            ("implementing", "reviewing-implementation"),
            ("reviewing-implementation", "reviewed-implementation"),
            ("reviewed-implementation", "polishing-implementation"),
            ("polishing-implementation", "implemented"),
            ("implemented", "release"),
            ("release", "done"),
        ]
        for from_s, to_s in forward_cases:
            # Domain
            assert workflow.is_forward_transition(from_s, to_s), (
                f"Domain should accept {from_s} -> {to_s}"
            )
            # CLI
            result = _run_service_client(
                db_path, "validate-transition", from_s, to_s,
                "--workflow", "epic",
            )
            assert result.returncode == 0, (
                f"CLI should accept {from_s} -> {to_s}"
            )

    def test_backward_transitions_rejected(self, parity_env):
        """Backward transitions should be rejected by both surfaces."""
        db_path = parity_env["db_path"]
        workflow = builtin_workflow_runtime("epic")

        backward_cases = [
            ("done", "planning"),
            ("planned", "idea"),
            ("release", "implementing"),
        ]
        for from_s, to_s in backward_cases:
            # Domain
            assert not workflow.is_forward_transition(from_s, to_s), (
                f"Domain should reject {from_s} -> {to_s}"
            )
            # CLI
            result = _run_service_client(
                db_path, "validate-transition", from_s, to_s,
                "--workflow", "epic",
            )
            assert result.returncode == 1, (
                f"CLI should reject {from_s} -> {to_s}"
            )

    def test_exceptional_transitions_not_forward(self, parity_env):
        """Transitions involving exceptional statuses are not forward moves."""
        db_path = parity_env["db_path"]
        workflow = builtin_workflow_runtime("epic")

        cases = [
            ("planning", "blocked"),
            ("blocked", "planning"),
        ]
        for from_s, to_s in cases:
            assert not workflow.is_forward_transition(from_s, to_s)
            result = _run_service_client(
                db_path, "validate-transition", from_s, to_s,
                "--workflow", "epic",
            )
            assert result.returncode == 1

    def test_issue_workflow_parity(self, parity_env):
        """CLI issue selection matches the built-in workflow runtime."""
        db_path = parity_env["db_path"]
        workflow = builtin_workflow_runtime("issue")

        # planning is in epic progression but not issue progression
        assert not workflow.is_forward_transition("refined-idea", "planning")
        result = _run_service_client(
            db_path, "validate-transition", "refined-idea", "planning",
            "--workflow", "issue",
        )
        assert result.returncode == 1, "CLI should reject refined-idea->planning for issue"

        # refined-idea -> implementing is valid for issues
        assert workflow.is_forward_transition("refined-idea", "implementing")
        result = _run_service_client(
            db_path, "validate-transition", "refined-idea", "implementing",
            "--workflow", "issue",
        )
        assert result.returncode == 0, "CLI should accept refined-idea->implementing for issue"

    def test_epic_workflow_parity(self, parity_env):
        """CLI epic selection matches the built-in workflow runtime."""
        db_path = parity_env["db_path"]
        workflow = builtin_workflow_runtime("epic")

        assert workflow.is_forward_transition("refined-idea", "planning")
        result = _run_service_client(
            db_path, "validate-transition", "refined-idea", "planning",
            "--workflow", "epic",
        )
        assert result.returncode == 0, "CLI should accept refined-idea->planning for epic"


# ===========================================================================
# Group 9: Mutation-layer gate parity
# ===========================================================================


class TestGateParity:
    """Verify that gates enforced by the mutation layer produce consistent
    rejections across both API and service-client surfaces."""

    def test_done_without_nonce_rejected_both(self, write_parity_env):
        """Both surfaces should reject setting status=done without the
        done-ceremony nonce (unless force is set)."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # API — item 1 is implementing, try to set done without nonce
        api_resp = client.patch("/v1/items/1", json={"status": "done"})
        assert api_resp.status_code == 409

        # CLI
        cli_result = _run_service_client(
            db_path, "update-item", "1",
            "--field", "status", "--value", "done",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False
        assert "GATE_DONE_NONCE" in cli_data.get("error_code", "")

    def test_validate_without_qa_requirements_rejected_both(self, write_parity_env):
        """Both surfaces should reject transition to reviewing-implementation without
        qa_requirements rows."""
        client = write_parity_env["client"]
        db_path = write_parity_env["db_path"]

        # Item 1 uses the issue workflow — reviewing-implementation is
        # valid here, so the QA gate check is reached.
        api_resp = client.patch("/v1/items/1", json={"status": "reviewing-implementation"})
        assert api_resp.status_code == 409

        cli_result = _run_service_client(
            db_path, "update-item", "1",
            "--field", "status", "--value", "reviewing-implementation",
        )
        assert cli_result.returncode == 1
        cli_data = json.loads(cli_result.stdout)
        assert cli_data["success"] is False
        assert "GATE_QA_REVIEWING" in cli_data.get("error_code", "")
