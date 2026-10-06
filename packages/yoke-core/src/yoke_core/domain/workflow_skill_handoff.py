"""Name the bound-skill handoff a lifecycle transition crossed.

Skill bindings assign each non-terminal stage to one skill's half-open
segment. A transition whose target sits in a different segment than its
source hands the item to another skill — the next leg is a fresh command
and claim. The transition still happens; the response names the handoff,
rendered from the pinned binding, so no caller restates the routing.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import FunctionWarning


def _bound_skill(workflow: Any, stage_id: str) -> str:
    binding = workflow.skill_binding_for_stage(stage_id)
    return str(binding["skill_id"]) if binding is not None else ""


def skill_handoff(
    workflow: Any, source_status: str, target_status: str
) -> Optional[dict[str, str]]:
    """The handoff ``source -> target`` crossed, or ``None`` within a segment.

    A terminal target ends every segment and hands to no skill, so it is not
    a handoff either.
    """
    to_skill = _bound_skill(workflow, target_status)
    if not to_skill:
        return None
    from_skill = _bound_skill(workflow, source_status)
    if from_skill == to_skill:
        return None
    return {
        "from_skill_id": from_skill,
        "to_skill_id": to_skill,
        "stage_id": target_status,
        "next_command": f"/yoke {to_skill}",
    }


def item_skill_handoff(
    item_id: int, source_status: str, target_status: str
) -> tuple[Optional[dict[str, str]], list[FunctionWarning]]:
    """The handoff for one item, read from its own pinned definition.

    Read after the transition committed, so a failed read is reported as a
    named warning beside the successful write rather than as its failure.
    """
    from yoke_core.domain import db_helpers
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    try:
        with db_helpers.connect() as conn:
            workflow = load_item_workflow_runtime(conn, int(item_id))
    except Exception as exc:  # noqa: BLE001 - the write already committed
        return None, [
            FunctionWarning(
                code="skill_handoff_unread",
                step="skill_handoff",
                detail=(
                    f"the transition committed, but its pinned definition "
                    f"could not be re-read to name the next skill ({exc}); "
                    "read it with `yoke workflows item get`."
                ),
            )
        ]
    return skill_handoff(workflow, source_status, target_status), []


__all__ = ["item_skill_handoff", "skill_handoff"]
