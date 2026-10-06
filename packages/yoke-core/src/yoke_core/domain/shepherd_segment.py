"""Planning edges and verdict identities from the pinned Shepherd binding."""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.domain.workflow_runtime import WorkflowRuntime
from yoke_core.domain.workflow_registry import WorkflowRegistryError


@dataclass(frozen=True)
class ShepherdEdge:
    source_stage: str
    target_stage: str

    @property
    def verdict_key(self) -> str:
        return f"{self.source_stage.replace('-', '_')}_to_{self.target_stage.replace('-', '_')}"


def shepherd_edges(runtime: WorkflowRuntime) -> tuple[ShepherdEdge, ...]:
    """Read the ordered, declared edges; absent bindings own no verdicts."""
    bindings = [
        row
        for row in runtime.definition["skill_bindings"]
        if row["skill_id"] == "shepherd"
    ]
    if not bindings:
        return ()
    if len(bindings) != 1:
        raise WorkflowRegistryError(
            "shepherd_binding_ambiguous: publish a workflow version with one Shepherd binding"
        )
    binding = bindings[0]
    stages = runtime.stage_ids
    start = stages.index(binding["from_stage_id"])
    stop = stages.index(binding["through_stage_id"])
    segment = stages[start : stop + 1]
    edges = tuple(
        ShepherdEdge(source, target) for source, target in zip(segment, segment[1:])
    )
    declared = {
        (row["from_stage_id"], row["to_stage_id"])
        for row in runtime.definition["transitions"]
    }
    if not edges or any(
        (edge.source_stage, edge.target_stage) not in declared for edge in edges
    ):
        raise WorkflowRegistryError(
            "shepherd_segment_unsupported: publish a binding with declared consecutive planning edges"
        )
    if len({edge.verdict_key for edge in edges}) != len(edges):
        raise WorkflowRegistryError(
            "shepherd_verdict_key_collision: publish stage names with distinct normalized edge keys"
        )
    return edges
