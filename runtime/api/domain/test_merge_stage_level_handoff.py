"""A composed merge returns a worker handoff without terminal cleanup."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge_close_out_transition as transition
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute
from yoke_core.domain.workflow_level_handoff import record_level_handoff


def test_merge_returns_stage_handoff_before_cleanup_or_release_wait(monkeypatch):
    handoff = {
        "reason": "level_change",
        "stage_id": "release",
        "level": "JUNIOR",
        "next_command": "successor command",
    }
    monkeypatch.setattr(transition, "_refresh_lane_head", lambda *_a: None)
    monkeypatch.setattr(
        transition,
        "close_out_route",
        lambda *_a, **_k: CloseOutRoute(stages=("release", "done")),
    )
    monkeypatch.setattr(
        transition,
        "retain_if_waiting",
        lambda *_a, **_k: pytest.fail("handoff precedes delivery park"),
    )

    def close(**_kwargs):
        record_level_handoff({"handoff": handoff})
        return "release", ""

    envelope = {}
    phases = []
    result = transition.run_terminal_transition(
        item={"id": 7},
        item_id=7,
        public_ref="ITEM-7",
        branch="item-branch",
        target="main",
        status="reviewing-implementation",
        close_lane=LandedLane(
            branch="item-branch", target="main", commit_sha="1" * 40, merge_sha="2" * 40
        ),
        session_id="worker",
        repo_root=Path("/repo"),
        envelope=envelope,
        announce=phases.append,
        close_out=SimpleNamespace(transition_to_done=close),
        evidence=SimpleNamespace(CLOSED_OUT_STATUS="done"),
        pending=None,
        record_terminal_lane_close_out=lambda **_k: pytest.fail(
            "successor needs its lane"
        ),
    )
    assert result is None
    assert envelope == {"status": "release", "handoff": handoff}
    assert phases == ["terminal transition", "level-change handoff"]
