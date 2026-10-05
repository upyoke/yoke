"""Lifecycle transitions name the bound-skill handoff they cross."""

from __future__ import annotations

from yoke_core.domain.workflow_runtime import builtin_workflow_runtime
from yoke_core.domain.workflow_skill_handoff import skill_handoff


def test_crossing_into_another_binding_names_its_skill():
    runtime = builtin_workflow_runtime("issue")
    handoff = skill_handoff(
        runtime, "reviewing-implementation", "reviewed-implementation"
    )
    assert handoff is not None
    assert handoff["to_skill_id"] == "polish"
    assert handoff["stage_id"] == "reviewed-implementation"
    assert handoff["next_command"] == "/yoke polish"


def test_a_move_inside_one_binding_is_not_a_handoff():
    runtime = builtin_workflow_runtime("dash")
    assert skill_handoff(runtime, "idea", "implementing") is None
    assert skill_handoff(runtime, "implementing", "reviewing-implementation") is None


def test_a_terminal_target_hands_to_no_skill():
    runtime = builtin_workflow_runtime("dash")
    assert skill_handoff(runtime, "release", "done") is None
