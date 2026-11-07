"""Workflow pins own terminal membership and generated task progress."""

from __future__ import annotations

import ast
import re
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
                "migrations" in path.parts
                or path.name == "lifecycle_status.py"
            ):
                continue
            tree = ast.parse(path.read_text())
            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(
                    node,
                    (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }

            def stage_operand(value):
                if isinstance(value, ast.Name):
                    return value.id == "status" or value.id.endswith("_status")
                if isinstance(value, ast.Attribute):
                    return value.attr == "status" or value.attr.endswith("_status")
                return (
                    isinstance(value, ast.Subscript)
                    and isinstance(value.slice, ast.Constant)
                    and value.slice.value == "status"
                )

            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    operands = [node.left, *node.comparators]
                    if any(
                        isinstance(value, ast.Constant)
                        and value.value in ("done", "release")
                        for value in operands
                    ) and any(stage_operand(value) for value in operands):
                        violations.append(f"{path.relative_to(root)}:{node.lineno}")
                if (
                    isinstance(node, ast.Constant)
                    and id(node) not in docstrings
                    and isinstance(node.value, str)
                    and re.search(
                        r"\bstatus\s*(?:=|<>|(?:NOT )?IN)\s*(?:\([^)]*)?'(?:done|release)'",
                        node.value,
                        re.IGNORECASE,
                    )
                ):
                    violations.append(f"{path.relative_to(root)}:{node.lineno}")
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
