"""Summary and full projections of resolved operator instructions."""

from typing import Any, Dict, List
from yoke_contracts.read_detail import DETAIL_FULL, excerpt
from yoke_core.domain.execution_instruction_delivery import (
    DELIVERY_FIELDS,
    DeliveryPoint,
)


def resolve_read_command(
    workflow: str,
    project: str,
    *,
    delivery_point: DeliveryPoint = "before_creation",
    stage_bucket: str | None = None,
) -> str:
    """The command that serves this scope's instruction prose in full."""
    selection = (
        f" --delivery-point {delivery_point}"
        if delivery_point != "before_creation"
        else ""
    )
    selection += f" --stage-bucket {stage_bucket}" if stage_bucket else ""
    return (
        "yoke workflow execution-instruction resolve "
        f"--workflow {workflow} --project {project}{selection} --full"
    )


def resolve_projection(
    instructions: List[Dict[str, Any]],
    *,
    workflow: str,
    project: str,
    detail: str,
    delivery_point: DeliveryPoint = "before_creation",
    stage_bucket: str | None = None,
) -> List[Dict[str, Any]]:
    """Serve the prose on ``full``, and one descriptor each otherwise."""
    if detail == DETAIL_FULL:
        return instructions
    return instruction_descriptors(
        instructions,
        read=resolve_read_command(
            workflow, project, delivery_point=delivery_point, stage_bucket=stage_bucket
        ),
    )


def instruction_descriptors(
    instructions: List[Dict[str, Any]], *, read: str
) -> List[Dict[str, Any]]:
    """Describe matching instructions and name their full read."""
    return [
        {
            "id": instruction["id"],
            "title": excerpt(instruction.get("content")),
            "content_characters": len(str(instruction.get("content") or "")),
            "applies_to_all_workflows": instruction["applies_to_all_workflows"],
            "applies_to_all_projects": instruction["applies_to_all_projects"],
            **{key: instruction[key] for key in DELIVERY_FIELDS},
            "read": read,
        }
        for instruction in instructions
    ]
