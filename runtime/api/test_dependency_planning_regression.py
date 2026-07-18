"""End-to-end regression scenarios for the dependency-planning kernel.

Covers (originally task 7 of the dependency-planning work):
- Activation-gate blocking lifecycle
- Integration-gate parallel-code / serialized-merge semantics
- Fan-out from a foundation item at the integration gate
- Mixed activation/integration edges (operator plan parity)
- Rationale visibility through gate evaluation, plan, and serialization
- Telemetry envelope (session_id, project, unsatisfied summary)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.dependency_planning import (
    evaluate_batch_gates,
    evaluate_item_gate,
    plan_candidate_set,
)
from runtime.api.test_dependency_planning_helpers import (
    create_test_db as _create_test_db,
    insert_dep as _insert_dep,
    insert_item as _insert_item,
)


# ---------------------------------------------------------------------------
# Task 7: End-to-end regression scenarios
# ---------------------------------------------------------------------------


class TestActivationBlockingRegression:
    """Regression: activation gate blocks coding frontier until blocker done."""

    def test_blocked_then_unblocked_lifecycle(self):
        """B depends on A at activation/status:done. B is blocked until A done."""
        conn = _create_test_db()
        _insert_item(conn, 1, title="Item A", status="implementing")
        _insert_item(conn, 2, title="Item B", status="planned")
        _insert_dep(conn, "YOK-2", "YOK-1", "activation", "status:done",
                    rationale="B needs A done first")

        # B blocked at activation while A is still implementing
        result = evaluate_item_gate(conn, "YOK-2", "activation")
        assert result.is_blocked is True
        assert len(result.unsatisfied_blockers) == 1
        assert result.unsatisfied_blockers[0].blocking_item == "YOK-1"

        # A not blocked (no deps)
        result_a = evaluate_item_gate(conn, "YOK-1", "activation")
        assert result_a.is_blocked is False

        # Advance A to done -> B unblocked
        conn.execute("UPDATE items SET status='done' WHERE id=1")
        result = evaluate_item_gate(conn, "YOK-2", "activation")
        assert result.is_blocked is False

    def test_frontier_excludes_activation_blocked(self):
        """plan_candidate_set excludes activation-blocked items from eligible."""
        conn = _create_test_db()
        _insert_item(conn, 1, title="Blocker", status="implementing")
        _insert_item(conn, 2, title="Dependent", status="planned")
        _insert_dep(conn, "YOK-2", "YOK-1", "activation", "status:done")

        result = plan_candidate_set(conn, ["YOK-1", "YOK-2"], "activation")
        assert "YOK-1" in result.eligible
        blocked_ids = [c.item_id for c in result.blocked]
        assert "YOK-2" in blocked_ids


class TestIntegrationBlockingRegression:
    """Regression: integration gate permits parallel coding but serializes merge."""

    def test_both_codeable_only_one_mergeable(self):
        """A and B can code in parallel but B cannot merge until A is merged."""
        conn = _create_test_db()
        _insert_item(conn, 1, title="Item A", status="reviewing-implementation")
        _insert_item(conn, 2, title="Item B", status="reviewing-implementation")
        _insert_dep(conn, "YOK-2", "YOK-1", "integration", "fact:merged",
                    rationale="B merges after A")

        # Both eligible at activation (no activation deps)
        act_plan = plan_candidate_set(conn, ["YOK-1", "YOK-2"], "activation")
        assert set(act_plan.eligible) == {"YOK-1", "YOK-2"}

        # B blocked at integration, A eligible
        int_plan = plan_candidate_set(conn, ["YOK-1", "YOK-2"], "integration")
        assert "YOK-1" in int_plan.eligible
        blocked_ids = [c.item_id for c in int_plan.blocked]
        assert "YOK-2" in blocked_ids

        # Merge A -> B becomes eligible at integration
        conn.execute("UPDATE items SET merged_at='2026-01-15T00:00:00Z' WHERE id=1")
        int_plan = plan_candidate_set(conn, ["YOK-1", "YOK-2"], "integration")
        assert set(int_plan.eligible) == {"YOK-1", "YOK-2"}


class TestParallelCodeSerializedMergeRegression:
    """Regression: fan-out from foundation item at integration gate."""

    def test_fan_out_integration_deps(self):
        """A is foundation; B and C depend on A at integration. All code in parallel."""
        conn = _create_test_db()
        _insert_item(conn, 1, title="Foundation A", status="implementing")
        _insert_item(conn, 2, title="Worker B", status="implementing")
        _insert_item(conn, 3, title="Worker C", status="implementing")
        _insert_dep(conn, "YOK-2", "YOK-1", "integration", "fact:merged")
        _insert_dep(conn, "YOK-3", "YOK-1", "integration", "fact:merged")

        # All eligible at activation (no activation deps)
        act = plan_candidate_set(conn, ["YOK-1", "YOK-2", "YOK-3"], "activation")
        assert set(act.eligible) == {"YOK-1", "YOK-2", "YOK-3"}

        # Only A eligible at integration
        integ = plan_candidate_set(conn, ["YOK-1", "YOK-2", "YOK-3"], "integration")
        assert integ.eligible == ["YOK-1"]
        blocked_ids = sorted([c.item_id for c in integ.blocked])
        assert blocked_ids == ["YOK-2", "YOK-3"]

        # Merge A -> B and C become eligible
        conn.execute("UPDATE items SET merged_at='2026-01-15T00:00:00Z' WHERE id=1")
        integ = plan_candidate_set(conn, ["YOK-1", "YOK-2", "YOK-3"], "integration")
        assert set(integ.eligible) == {"YOK-1", "YOK-2", "YOK-3"}


class TestOperatorPlanParityRegression:
    """Regression: mixed activation/integration edges produce consistent plans."""

    def test_wave_plan_consistency(self):
        """Wave plan: H->I,J at activation; I->K at activation; J->K at integration."""
        conn = _create_test_db()
        _insert_item(conn, 30, title="H - foundation", status="planned")
        _insert_item(conn, 31, title="I - wave 2a", status="idea")
        _insert_item(conn, 32, title="J - wave 2b", status="idea")
        _insert_item(conn, 33, title="K - wave 3", status="idea")

        _insert_dep(conn, "YOK-31", "YOK-30", "activation", "status:done")
        _insert_dep(conn, "YOK-32", "YOK-30", "activation", "status:done")
        _insert_dep(conn, "YOK-33", "YOK-31", "activation", "status:done")
        _insert_dep(conn, "YOK-33", "YOK-32", "integration", "fact:merged")

        # Only H eligible at activation
        plan = plan_candidate_set(
            conn, ["YOK-30", "YOK-31", "YOK-32", "YOK-33"], "activation")
        assert plan.eligible == ["YOK-30"]

        # H done -> I, J eligible at activation; K still blocked
        conn.execute("UPDATE items SET status='done' WHERE id=30")
        plan = plan_candidate_set(
            conn, ["YOK-30", "YOK-31", "YOK-32", "YOK-33"], "activation")
        assert "YOK-31" in plan.eligible
        assert "YOK-32" in plan.eligible
        blocked_ids = [c.item_id for c in plan.blocked]
        assert "YOK-33" in blocked_ids

        # I done -> K activation-eligible
        conn.execute("UPDATE items SET status='done' WHERE id=31")
        plan = plan_candidate_set(
            conn, ["YOK-30", "YOK-31", "YOK-32", "YOK-33"], "activation")
        assert "YOK-33" in plan.eligible

        # K still integration-blocked (J not merged)
        gate = evaluate_item_gate(conn, "YOK-33", "integration")
        assert gate.is_blocked is True

        # J merged -> K integration-clear
        conn.execute("UPDATE items SET merged_at='2026-01-20T00:00:00Z' WHERE id=32")
        gate = evaluate_item_gate(conn, "YOK-33", "integration")
        assert gate.is_blocked is False


class TestRationaleVisibilityRegression:
    """Regression: rationale and evidence propagate through all surfaces."""

    def test_rationale_in_gate_evaluation(self):
        conn = _create_test_db()
        _insert_item(conn, 50, title="Target", status="idea")
        _insert_item(conn, 51, title="Blocker", status="implementing")
        _insert_dep(conn, "YOK-50", "YOK-51", "activation", "status:done",
                    rationale="Schema migration must land before API consumer")

        result = evaluate_item_gate(conn, "YOK-50", "activation")
        assert result.is_blocked is True
        bd = result.unsatisfied_blockers[0]
        assert bd.rationale == "Schema migration must land before API consumer"
        assert bd.blocking_item == "YOK-51"
        assert bd.satisfaction == "status:done"
        assert len(bd.reason) > 0  # Runtime evaluation reason

    def test_rationale_in_plan_candidates(self):
        conn = _create_test_db()
        _insert_item(conn, 50, title="Target", status="idea")
        _insert_item(conn, 51, title="Blocker", status="implementing")
        _insert_dep(conn, "YOK-50", "YOK-51", "activation", "status:done",
                    rationale="Must complete migration first")

        plan = plan_candidate_set(conn, ["YOK-50", "YOK-51"], "activation")
        blocked_item = [c for c in plan.blocked if c.item_id == "YOK-50"][0]
        assert len(blocked_item.blockers) == 1
        assert blocked_item.blockers[0].rationale == "Must complete migration first"

    def test_rationale_in_to_dict_serialization(self):
        conn = _create_test_db()
        _insert_item(conn, 50, title="Target", status="idea")
        _insert_item(conn, 51, title="Blocker", status="implementing")
        _insert_dep(conn, "YOK-50", "YOK-51", "activation", "status:done",
                    rationale="API contract dependency")

        result = evaluate_item_gate(conn, "YOK-50", "activation")
        d = result.to_dict()
        assert d["unsatisfied_blockers"][0]["rationale"] == "API contract dependency"
        assert "reason" in d["unsatisfied_blockers"][0]


class TestDependencyPlanningTelemetry:
    @patch("yoke_core.domain.events.emit_event")
    def test_batch_gate_event_carries_session_id_project_and_summary(self, mock_emit):
        conn = _create_test_db()
        _insert_item(conn, 1, status="idea")
        _insert_item(conn, 2, status="implementing")
        _insert_dep(
            conn,
            "YOK-1",
            "YOK-2",
            "activation",
            "status:done",
            rationale="Finish blocker first",
        )

        evaluate_batch_gates(
            conn,
            "activation",
            session_id="sess-gates",
            project="externalwebapp",
        )

        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["session_id"] == "sess-gates"
        assert kwargs["project"] == "externalwebapp"
        summary = kwargs["context"]["unsatisfied_summary"]
        assert summary[0]["item_id"] == "YOK-1"
        assert summary[0]["blocking_item"] == "YOK-2"
        assert summary[0]["gate_point"] == "activation"
        assert summary[0]["satisfaction"] == "status:done"
        assert summary[0]["rationale"] == "Finish blocker first"
