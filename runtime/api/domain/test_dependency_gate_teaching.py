"""Unmet dependencies teach which work can continue on every notice route."""

from types import SimpleNamespace

import pytest

from yoke_core.domain.dependency_satisfied_notice import satisfied_message
from yoke_core.domain.integration_dependency_refusal import integration_dependency_refusal
from yoke_core.domain.session_launch_mandate import compose_single_item_mandate


@pytest.mark.parametrize("route", ["holder", "steering"])
@pytest.mark.parametrize(
    ("gate", "action"),
    [
        ("activation", "do not start or staff yet"),
        ("integration", "work, test and open the pull request now; merge only after it clears"),
        ("closure", "work and merge now; close only after it clears"),
    ],
)
def test_remaining_gate_names_the_held_step(route, gate, action):
    body = satisfied_message(
        route,
        blocker_ref="blocker",
        dependent_ref="dependent",
        event="merged",
        gate_point="integration",
        satisfaction="fact:merged",
        remaining=[{"blocker_ref": "other", "gate_point": gate,
                    "satisfaction": "status:done"}],
    )
    assert f"other {gate} gate status:done: {action}" in body
    assert "keep waiting on those" not in body
    if gate != "activation":
        assert "do not staff" not in body


def test_mixed_gates_keep_each_action_scoped_to_its_gate():
    body = satisfied_message(
        "holder", blocker_ref="blocker", dependent_ref="dependent", event="merged",
        gate_point="integration", satisfaction="fact:merged",
        remaining=[{"blocker_ref": gate, "gate_point": gate,
                    "satisfaction": "status:done"}
                   for gate in ("activation", "integration", "closure")],
    )
    assert "activation gate status:done: do not start or staff yet" in body
    assert "integration gate status:done: work, test and open the pull request now" in body
    assert "closure gate status:done: work and merge now; close only after it clears" in body


def test_launch_brief_teaches_gate_points_before_worker_can_park():
    ref = "ITEM-" + str(12)
    body = compose_single_item_mandate(
        public_ref=ref, entrypoint=f"/yoke dash {ref}", remaining_legs="merge/evidence close",
    )
    assert "activation means do not start or staff yet" in body
    assert "integration means work, test and open the pull request now" in body
    assert "merging only after it clears" in body
    assert "closure means work and merge now" in body
    assert "closing only after it clears. Park only at the held step." in body


def test_merge_refusal_allows_work_until_the_merge_step():
    body = integration_dependency_refusal(
        item_id=12, public_ref="ITEM-" + str(12),
        dispatch=lambda **_: SimpleNamespace(success=True, result={
            "is_blocked": True,
            "unsatisfied_blockers": [{"blocking_item": "blocker"}],
        }),
    )
    assert "Work, test and open the pull request now; only the merge is held" in body
    assert "At the merge step, keep your work claim and lane" in body
