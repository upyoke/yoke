"""Reviewed-implementation authoritative-gate aggregation regressions."""

from __future__ import annotations

import contextlib
from unittest import mock

from yoke_core.domain import backlog_updates_helpers as helpers
from yoke_core.domain.backlog_authoritative_status_gate import (
    _run_authoritative_status_gate,
)
from yoke_core.domain.qa_gate_definitions import GateResult


# Reviewed-implementation aggregation regression.
# Reviewed-negative-claim coverage lives in
# test_backlog_updates_helpers_reviewed_none.py.


def _aggregate_reviewed(*, arch=None, boundary=None, qa=None, item_id: int = 42):
    """Patch every gate the reviewed-implementation aggregator dispatches and
    invoke the composer. ``None`` => gate passes."""
    from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

    qa_default = qa if qa is not None else GateResult(passed=True)
    with contextlib.ExitStack() as s:
        s.enter_context(
            mock.patch(
                "yoke_core.domain.backlog_authoritative_status_gate.load_item_workflow_runtime",
                return_value=builtin_workflow_runtime("issue"),
            )
        )
        s.enter_context(
            mock.patch.object(helpers, "_run_db_mutation_gate", return_value=None)
        )
        s.enter_context(
            mock.patch.object(helpers, "_run_file_line_gate", return_value=None)
        )
        s.enter_context(
            mock.patch(
                "yoke_core.domain.backlog_architecture_gate_runner._run_architecture_impact_gate",
                return_value=arch,
            )
        )
        s.enter_context(
            mock.patch(
                "yoke_core.domain.path_claims_gate_boundary.check_boundary_for_item",
                return_value=boundary,
            )
        )
        s.enter_context(
            mock.patch(
                "yoke_core.domain.qa_gates.check_verification_gate",
                return_value=qa_default,
            )
        )
        return _run_authoritative_status_gate(
            item_id=item_id,
            target_status="reviewed-implementation",
            db_path="/tmp/fake.db",
            qa_bypass=False,
            force=False,
        )


def test_reviewed_implementation_aggregates_boundary_and_qa_failures() -> None:
    """AC-50 / AC-52: two simultaneous independent blockers surface in
    ``failures`` while legacy top-level fields mirror the first."""
    boundary = {
        "success": False,
        "error": "path-claim boundary blocked.",
        "error_code": "GATE_PATH_CLAIM_BOUNDARY",
    }
    qa = GateResult(passed=False, errors=["verification unsatisfied."])
    result = _aggregate_reviewed(boundary=boundary, qa=qa)
    assert result["success"] is False
    assert result["transitioned"] is False
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "boundary" in result["error"]
    failures = result["failures"]
    assert [f["gate_id"] for f in failures] == [
        "path_claim_boundary",
        "qa_verification",
    ]
    codes = [f["error_code"] for f in failures]
    assert "GATE_PATH_CLAIM_BOUNDARY" in codes
    assert "GATE_QA_REVIEWED_IMPLEMENTATION" in codes
    for entry in failures:
        assert set(entry.keys()) == {
            "gate_id",
            "error_code",
            "error_message",
            "remediation_hint",
        }


def test_reviewed_implementation_aggregates_all_three_independent_failures() -> None:
    arch = {
        "success": False,
        "error": "arch blocked.",
        "error_code": "GATE_ARCHITECTURE_IMPACT",
    }
    boundary = {
        "success": False,
        "error": "boundary blocked.",
        "error_code": "GATE_PATH_CLAIM_BOUNDARY",
    }
    qa = GateResult(passed=False, errors=["qa unsatisfied."])
    result = _aggregate_reviewed(arch=arch, boundary=boundary, qa=qa, item_id=99)
    assert result["error_code"] == "GATE_ARCHITECTURE_IMPACT"
    assert [f["gate_id"] for f in result["failures"]] == [
        "architecture_impact",
        "path_claim_boundary",
        "qa_verification",
    ]


def test_reviewed_implementation_all_pass_returns_none() -> None:
    assert _aggregate_reviewed() is None
