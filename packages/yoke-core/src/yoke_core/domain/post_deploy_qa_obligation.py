"""Whether an item owes a post-deploy QA answer, and how to give one.

An item whose delivery flow declares an item-scoped QA stage is asked,
after deployment, to prove its own behaviour. The answer is cheapest while
the item is still in hand, so the question is surfaced as early as the item
exists: at filing, at worktree preparation, on ``yoke items get``, and as a
landing blocker at merge.

Every surface reaches one :class:`PostDeployObligation` from the same two
facts — the flow's stages and the item's own answer rows — so the filing
notice, the item read and the merge refusal cannot disagree. The control
plane builds it from a connection; installed-client code builds it from the
relayed item detail it already holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_core.domain.post_deploy_verification_answer import (
    UNANSWERED,
    PostDeployAnswer,
    answer_from_item_detail,
    attach_standing_recipe,
    record_no_obligation_recipe,
)
from yoke_core.domain.qa_item_stage_plan_gate import (
    DEFAULT_ATTACHMENT_TRANSITION,
    stages_declare_item_scoped_qa,
)

#: The flow asks this item nothing after deployment.
NOT_OWED = "not_owed"


@dataclass(frozen=True)
class PostDeployObligation:
    """One item's post-deploy QA status and, when unanswered, its answers."""

    status: str
    flow_id: str = ""
    answer_with: tuple[str, ...] = ()

    @property
    def unanswered(self) -> bool:
        return self.status == UNANSWERED

    def summary(self) -> str:
        """One line naming the status and, when owed, both ways to answer."""
        if self.status == NOT_OWED:
            return "not owed"
        text = self.status.replace("_", " ")
        if not self.unanswered:
            return text
        return (
            f"unanswered (delivery flow {self.flow_id!r} has an item-scoped QA "
            "stage). Answer before merge: attach a post_deploy plan with `"
            + self.answer_with[0]
            + "`, or record that nothing is observable with `"
            + self.answer_with[1]
            + "`"
        )

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status, "summary": self.summary()}
        if self.flow_id:
            payload["flow_id"] = self.flow_id
        if self.answer_with:
            payload["answer_with"] = list(self.answer_with)
        return payload


def obligation(
    *,
    public_ref: str,
    project: str,
    flow_id: str,
    stages: Any,
    answer: PostDeployAnswer,
    transition: str,
) -> PostDeployObligation:
    """Combine the flow's stages with the item's answer."""
    if not flow_id or not stages_declare_item_scoped_qa(stages):
        return PostDeployObligation(NOT_OWED)
    answer_with: tuple[str, ...] = ()
    if answer.unanswered:
        answer_with = (
            attach_standing_recipe(public_ref, project=project, transition=transition),
            record_no_obligation_recipe(public_ref),
        )
    return PostDeployObligation(answer.verdict, flow_id, answer_with)


def obligation_from_detail(item: Mapping[str, Any]) -> PostDeployObligation | None:
    """Client-side status from a relayed ``items.detail.get`` item.

    ``None`` when the flow's stages could not be read: an unknown answer is
    never reported as either owed or clear.
    """
    from yoke_core.domain.qa_item_stage_plan_gate import (
        attachment_transition,
        completion_flow,
        flow_stages,
    )

    flow_id = completion_flow(item)
    if not flow_id:
        return PostDeployObligation(NOT_OWED)
    stages, notice = flow_stages(flow_id)
    if notice:
        return None
    if not stages_declare_item_scoped_qa(stages):
        return PostDeployObligation(NOT_OWED)
    project = item.get("project")
    slug = str(project.get("slug") or "") if isinstance(project, Mapping) else str(project or "")
    return obligation(
        public_ref=str(item.get("public_ref") or ""),
        project=slug,
        flow_id=flow_id,
        stages=stages,
        answer=answer_from_item_detail(item),
        transition=attachment_transition(item),
    )


def obligation_for_item(conn: Any, item_id: int) -> PostDeployObligation:
    """Control-plane status for one item, read through ``conn``."""
    from yoke_core.domain.db_helpers import query_scalar
    from yoke_core.domain.flow_crud import cmd_stages
    from yoke_core.domain.item_completion_flow_projection import (
        completion_flow_values,
    )
    from yoke_core.domain.post_deploy_verification_answer import answer_for_item
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.workflow_behavior import delivery_redirect_stage
    from yoke_core.domain.workflow_registry import WorkflowRegistryError
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    flow_id = str(
        (completion_flow_values(conn, [item_id]).get(item_id) or {}).get("value") or ""
    )
    if not flow_id:
        return PostDeployObligation(NOT_OWED)
    try:
        stages = cmd_stages(conn, flow_id)
    except LookupError:
        return PostDeployObligation(NOT_OWED)
    if not stages_declare_item_scoped_qa(stages):
        return PostDeployObligation(NOT_OWED)
    try:
        transition = (
            delivery_redirect_stage(load_item_workflow_runtime(conn, item_id))
            or DEFAULT_ATTACHMENT_TRANSITION
        )
    except (KeyError, ValueError, WorkflowRegistryError):
        transition = DEFAULT_ATTACHMENT_TRANSITION
    project = query_scalar(
        conn,
        "SELECT p.slug FROM items i JOIN projects p ON p.id = i.project_id "
        "WHERE i.id = %s",
        (item_id,),
    )
    return obligation(
        public_ref=render_item_ref(conn, item_id),
        project=str(project or ""),
        flow_id=flow_id,
        stages=stages,
        answer=answer_for_item(conn, item_id),
        transition=transition,
    )


__all__ = [
    "NOT_OWED",
    "PostDeployObligation",
    "obligation",
    "obligation_for_item",
    "obligation_from_detail",
]
