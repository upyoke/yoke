"""Workflow pins own terminal membership and generated task progress."""

from __future__ import annotations

import ast
from pathlib import Path
from copy import deepcopy

from yoke_contracts.lifecycle_status import (
    successful_task_stage_ids,
    terminal_stage_ids,
)
from yoke_core.domain.workflow_runtime import WorkflowRuntime, builtin_workflow_runtime
from yoke_core.domain.qa_gate_definitions import status_settles_blocking_qa
from yoke_core.domain.queries import classify_item_state


def custom_runtime():
    base = builtin_workflow_runtime("epic")
    definition = deepcopy(base.definition)
    names = {
        stage["id"]: f"step-{index}" for index, stage in enumerate(definition["stages"])
    }
    for stage in definition["stages"]:
        stage["id"] = names[stage["id"]]
    for binding in definition["skill_bindings"]:
        for key in ("from_stage_id", "through_stage_id"):
            binding[key] = names[binding[key]]
    definition["terminal_stage_ids"] = [
        names[value] for value in definition["terminal_stage_ids"]
    ]
    return WorkflowRuntime("custom", 1, 1, "test", definition)


def test_success_follows_the_implementation_handoff_with_custom_names():
    runtime = custom_runtime()
    binding = next(
        b for b in runtime.definition["skill_bindings"] if b["skill_id"] == "conduct"
    )
    handoff = runtime.stage_ids.index(binding["through_stage_id"])
    expected = frozenset(runtime.stage_ids[handoff:])
    assert successful_task_stage_ids(runtime.definition) == expected
    assert runtime.successful_task_stage_ids == expected
    assert runtime.stage_ids[handoff - 1] not in expected
    assert "reviewed-implementation" not in expected


def test_terminal_and_qa_membership_follow_custom_completion():
    runtime = custom_runtime()
    completed = runtime.stage_ids[-1]
    assert terminal_stage_ids(runtime.definition) == frozenset(
        {completed, "cancelled", "stopped"}
    )
    assert "done" not in runtime.all_terminal_stage_ids
    assert status_settles_blocking_qa(completed, runtime)
    assert not status_settles_blocking_qa("done", runtime)
    assert not status_settles_blocking_qa("cancelled", runtime)
    assert (
        classify_item_state(completed, frozen=True, blocked=True, workflow=runtime)
        == "done"
    )


def test_production_code_has_no_copied_item_terminal_sets():
    root = Path(__file__).resolve().parents[3]
    violations = []
    for package in ("yoke-core", "yoke-contracts"):
        for path in (root / "packages" / package / "src").rglob("*.py"):
            if (
                "install_bundle_tree" in path.parts
                or "migrations" in path.parts
                or path.name == "lifecycle_status.py"
            ):
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, (ast.Set, ast.Tuple, ast.List)):
                    continue
                values = {
                    value.value
                    for value in node.elts
                    if isinstance(value, ast.Constant) and isinstance(value.value, str)
                }
                if (
                    "done" in values
                    and "cancelled" in values
                    or values == {"cancelled", "stopped"}
                ):
                    violations.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not violations, "Read the pinned workflow instead: " + ", ".join(violations)
