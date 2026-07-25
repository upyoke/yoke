"""Transition-graph and executor-binding validation for workflows."""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from yoke_core.domain.workflow_definition_builders import (
    REGISTERED_WORKFLOW_EXECUTOR_IDS,
)
from yoke_core.domain.workflow_definition_validation_support import (
    WorkflowDefinitionError,
    require_exact_keys,
    require_mapping,
    require_nonempty_text,
    require_sequence,
)

_TRANSITION_KEYS = frozenset({"from_stage_id", "to_stage_id"})
_BINDING_KEYS = frozenset({
    "executor_id",
    "from_stage_id",
    "through_stage_id",
})


def validate_transition_graph(
    definition: Mapping[str, Any],
    stage_ids: list[str],
    stage_id_set: set[str],
) -> list[tuple[str, str]]:
    """Validate reachability and return the declared transition edges."""
    terminals = [
        require_nonempty_text(value, "terminal_stage_ids[]")
        for value in require_sequence(
            definition.get("terminal_stage_ids"), "terminal_stage_ids"
        )
    ]
    if not terminals or not set(terminals) <= stage_id_set:
        raise WorkflowDefinitionError(
            "terminal_stage_ids must name at least one declared stage"
        )
    if len(terminals) != len(set(terminals)):
        raise WorkflowDefinitionError("terminal_stage_ids must be unique")

    edges: list[tuple[str, str]] = []
    for index, raw_transition in enumerate(
        require_sequence(definition.get("transitions"), "transitions")
    ):
        path = f"transitions[{index}]"
        transition = require_mapping(raw_transition, path)
        require_exact_keys(transition, _TRANSITION_KEYS, path)
        before = require_nonempty_text(
            transition.get("from_stage_id"), f"{path}.from_stage_id"
        )
        after = require_nonempty_text(
            transition.get("to_stage_id"), f"{path}.to_stage_id"
        )
        if before not in stage_id_set or after not in stage_id_set:
            raise WorkflowDefinitionError(
                f"{path} references an undeclared stage"
            )
        if before == after:
            raise WorkflowDefinitionError(f"{path} cannot be a self transition")
        edges.append((before, after))
    if len(edges) != len(set(edges)):
        raise WorkflowDefinitionError("transitions must be unique")

    outgoing: dict[str, set[str]] = {stage_id: set() for stage_id in stage_ids}
    incoming: dict[str, set[str]] = {stage_id: set() for stage_id in stage_ids}
    for before, after in edges:
        outgoing[before].add(after)
        incoming[after].add(before)
    for terminal in terminals:
        if outgoing[terminal]:
            raise WorkflowDefinitionError(
                f"terminal stage {terminal!r} cannot have outgoing transitions"
            )
    for stage_id in stage_ids:
        if stage_id not in terminals and not outgoing[stage_id]:
            raise WorkflowDefinitionError(
                f"non-terminal stage {stage_id!r} has no outgoing transition"
            )
    if incoming[stage_ids[0]]:
        raise WorkflowDefinitionError(
            "initial stage cannot have incoming transitions"
        )

    visited = {stage_ids[0]}
    pending = deque([stage_ids[0]])
    while pending:
        for candidate in outgoing[pending.popleft()]:
            if candidate not in visited:
                visited.add(candidate)
                pending.append(candidate)
    if visited != stage_id_set:
        missing = sorted(stage_id_set - visited)
        raise WorkflowDefinitionError(
            f"stages are unreachable from the initial stage: {missing}"
        )
    return edges


def validate_executor_bindings(
    definition: Mapping[str, Any],
    stage_ids: list[str],
    edges: list[tuple[str, str]],
) -> None:
    """Require registered executors to cover every declared transition."""
    stage_index = {stage_id: index for index, stage_id in enumerate(stage_ids)}
    covered: set[tuple[str, str]] = set()
    for index, raw_binding in enumerate(
        require_sequence(
            definition.get("executor_bindings"), "executor_bindings"
        )
    ):
        path = f"executor_bindings[{index}]"
        binding = require_mapping(raw_binding, path)
        require_exact_keys(binding, _BINDING_KEYS, path)
        executor_id = require_nonempty_text(
            binding.get("executor_id"), f"{path}.executor_id"
        )
        if executor_id not in REGISTERED_WORKFLOW_EXECUTOR_IDS:
            raise WorkflowDefinitionError(
                f"{path}.executor_id references unknown executor {executor_id!r}"
            )
        before = require_nonempty_text(
            binding.get("from_stage_id"), f"{path}.from_stage_id"
        )
        through = require_nonempty_text(
            binding.get("through_stage_id"), f"{path}.through_stage_id"
        )
        if before not in stage_index or through not in stage_index:
            raise WorkflowDefinitionError(f"{path} references an undeclared stage")
        if stage_index[before] >= stage_index[through]:
            raise WorkflowDefinitionError(
                f"{path} must cover at least one forward transition"
            )
        covered.update(
            edge for edge in edges
            if stage_index[before] <= stage_index[edge[0]]
            and stage_index[edge[1]] <= stage_index[through]
        )
    missing = [edge for edge in edges if edge not in covered]
    if missing:
        raise WorkflowDefinitionError(
            f"executor bindings do not cover transitions: {missing}"
        )


__all__ = ["validate_executor_bindings", "validate_transition_graph"]
