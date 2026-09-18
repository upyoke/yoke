"""A plan-less case in an ordered roster is drift-checked, not crashed on.

A deployment stage's roster carries the member's own requirements beside the
plan's, and a requirement belonging to no plan holds no case position — the
selection gives it one. The drift check read those two columns straight back
out of the row and converted them, so the first plan-less case in a roster
ended the run with ``int() argument ... not NoneType`` instead of any answer
a reader could act on.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.machine_qa_plan_case_snapshot import case_positions
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError


def _case(*, plan_id, case_position=1, baseline_position=1) -> dict:
    return {
        "requirement_id": 27748,
        "plan_id": plan_id,
        "case_position": case_position,
        "baseline_position": baseline_position,
    }


def test_a_plan_less_case_keeps_the_order_the_selection_gave_it() -> None:
    positions = case_positions(
        _case(plan_id=None, case_position=3),
        {"case_position": None, "baseline_position": None},
    )

    assert positions == (3, 1)


def test_a_planned_case_is_proved_against_the_positions_its_plan_assigned() -> None:
    positions = case_positions(
        _case(plan_id=431, case_position=2, baseline_position=4),
        {"case_position": 2, "baseline_position": 4},
    )

    assert positions == (2, 4)


def test_a_case_that_joined_a_plan_mid_execution_is_named_as_drift() -> None:
    with pytest.raises(QaPlanExecutionStateError) as refusal:
        case_positions(
            _case(plan_id=None),
            {"case_position": 1, "baseline_position": 1},
        )

    message = str(refusal.value)
    assert "joined a plan after this execution froze its roster" in message
    assert "yoke qa plan abort" in message


def test_a_planned_case_that_lost_its_positions_is_named_as_drift() -> None:
    with pytest.raises(QaPlanExecutionStateError) as refusal:
        case_positions(
            _case(plan_id=431),
            {"case_position": None, "baseline_position": None},
        )

    message = str(refusal.value)
    assert "lost the plan positions this execution froze" in message
    assert "yoke qa plan abort" in message
