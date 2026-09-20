"""Ask an item what it wants verified after its deploy, before it lands.

An item whose delivery flow carries an item-scoped QA stage will be asked,
after deployment, to prove its own behaviour on the deployed candidate. If
it reaches that wake having never been asked, the only moves left are bad
ones: borrow another item's plan and inherit criteria that were never about
this change, or author a probe under time pressure whose first execution is
against production, after the case has frozen. From there a defect can only
be waived or superseded.

Answering is cheap while the item is still in hand, and its cases are
editable right up to the moment one answers. So this refuses the landing
instead, where correcting it costs nothing.

The question has more than one right answer, so the refusal names each as
itself rather than demanding a plan: a standing attachment every future
deployment resolves, or a recorded no-obligation fact that nothing about
this item is observable once live. That fact is not a waiver.
:mod:`post_deploy_verification_answer` is the classifier both this gate
and the deployment QA stage read, so an item cannot be refused here as
unanswered and then read there as recorded.

The check reads the flow definition rather than any project's conventions:
an item is only asked when its own resolved flow declares a QA stage scoped
to items. A flow with no such stage, or none at all, is unaffected.

**The flow is the one that will close the item, not the column.**
``items.deployment_flow`` holds an explicit pin, and
:func:`yoke_core.domain.deployment_item_flow_resolution.freeze_item_completion_flow`
does not write the project default into it until the item is admitted to a
run — which happens after the merge. Reading that column here therefore
asked the question of almost nobody. The resolved answer travels on the item
detail payload as ``completion_flow``, the same explicit-pin-else-default
resolution every other delivery consumer uses.

Both facts it needs already travel over the serving control plane -- the
flow's stages through the ``deployment_flows.stages`` read, and the item's
attachments on the item detail payload the merge already holds. The gate
therefore opens no database connection of its own: the merge engine runs
client-side, where an https control plane has no local Postgres to connect
to, and it needs no server-side function that a not-yet-deployed control
plane would be missing.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any, Iterable

from yoke_core.domain.qa_deployment_member_attached_plans import (
    DEPLOYMENT_ATTACHMENT_PHASE,
)
from yoke_core.domain.post_deploy_verification_answer import (
    RUN_SCOPED_NOTE,
    answer_from_item_detail,
    attach_standing_recipe,
    record_no_obligation_recipe,
)

#: Where post-deploy acceptance binds when the workflow declares no
#: delivery wait of its own, matching what the attachment validator's own
#: refusal names.
DEFAULT_ATTACHMENT_TRANSITION = "done"


def _stages(raw: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw, list):
        decoded: Any = raw
    else:
        try:
            decoded = json.loads(str(raw or "[]"))
        except (TypeError, ValueError):
            return []
    if not isinstance(decoded, list):
        return []
    return [stage for stage in decoded if isinstance(stage, Mapping)]


def item_scoped_qa_stage_names(raw: Any) -> tuple[str, ...]:
    """Name every stage here that asks one member to answer for itself.

    Stage kinds are only ``execution`` or ``qa``, and an execution stage
    answers for the release, so an item-scoped QA stage is the whole of what
    a run can do about a single member.
    """
    return tuple(
        str(stage.get("name") or "")
        for stage in _stages(raw)
        if str(stage.get("stage_kind") or "") == "qa"
        and str(stage.get("scope") or "") == "item"
    )


def stages_declare_item_scoped_qa(raw: Any) -> bool:
    """True when these stages ask each member to answer for itself."""
    return bool(item_scoped_qa_stage_names(raw))


def has_attached_member_plan(attachments: Iterable[Any]) -> bool:
    """True when the item already attached a plan the QA stage will run."""
    return any(
        isinstance(attachment, Mapping)
        and str(attachment.get("qa_phase") or "").strip()
        == DEPLOYMENT_ATTACHMENT_PHASE
        for attachment in attachments
    )


def _relay(function_id: str, payload: dict[str, Any]) -> tuple[Any, str]:
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
    )
    if not response.success:
        return None, (
            response.error.message if response.error else "read failed"
        )
    return response.result or {}, ""


def attachment_transition(item: Mapping[str, Any]) -> str:
    """The stage a ``post_deploy`` attachment on this item may bind to.

    The rule belongs to :func:`delivery_redirect_stage`, which reads an
    immutable workflow definition, so this fetches the item's pinned version
    and asks it rather than restating the answer. An unreadable definition
    falls back to the terminal stage the binding validator itself names.
    """
    workflow = item.get("workflow")
    workflow = workflow if isinstance(workflow, Mapping) else {}
    workflow_id = str(workflow.get("id") or "").strip()
    version = workflow.get("version")
    if not workflow_id or version is None:
        return DEFAULT_ATTACHMENT_TRANSITION
    result, error = _relay(
        "workflows.version.get",
        {"workflow_id": workflow_id, "version": int(version)},
    )
    if error:
        return DEFAULT_ATTACHMENT_TRANSITION
    definition = (result or {}).get("definition")
    if not isinstance(definition, Mapping):
        return DEFAULT_ATTACHMENT_TRANSITION
    from yoke_core.domain.workflow_behavior import delivery_redirect_stage
    from yoke_core.domain.workflow_runtime import WorkflowRuntime

    try:
        redirect = delivery_redirect_stage(
            WorkflowRuntime(
                workflow_id=workflow_id,
                workflow_version_id=int(workflow.get("version_id") or 0),
                version=int(version),
                definition_digest="",
                definition=definition,
            )
        )
    except (KeyError, ValueError):
        return DEFAULT_ATTACHMENT_TRANSITION
    return redirect or DEFAULT_ATTACHMENT_TRANSITION


def flow_stages(flow_id: str) -> tuple[Any, str]:
    """Relay one flow's stage definitions. Returns ``(stages, notice)``."""
    result, error = _relay(
        "deployment_flows.stages", {"flow_id": str(flow_id)}
    )
    if error:
        return None, (
            f"could not read the stages of delivery flow {flow_id!r}, so "
            "whether this item owes its own QA plan was not established: "
            f"{error}"
        )
    return (result or {}).get("stages"), ""


def completion_flow(item: Mapping[str, Any]) -> str:
    """The flow that will close this item, as the detail read resolved it.

    ``deployment_flow`` is only the explicit pin and is empty on almost every
    item before it merges, so it is the fallback rather than the answer.
    """
    resolved = str(item.get("completion_flow") or "").strip()
    return resolved or str(item.get("deployment_flow") or "").strip()


def missing_item_qa_plan_refusal(
    item: Mapping[str, Any],
    *,
    public_ref: str,
) -> str:
    """Empty when this item may land, else why it may not and what to do."""
    flow_id = completion_flow(item)
    if not flow_id:
        return ""
    project = item.get("project")
    project_slug = (
        str(project.get("slug") or "")
        if isinstance(project, Mapping)
        else str(project or "")
    )
    if not project_slug:
        return ""
    stages, notice = flow_stages(flow_id)
    if notice:
        # Whether the named flow resolves at all belongs to delivery
        # clearance, which refuses an unresolvable one with its own reason.
        # Refusing here too would turn one fault into a second, worse-placed
        # merge blocker -- but a question this could not answer is never
        # passed off as a clear answer either.
        print(f"{public_ref}: {notice}", file=sys.stderr, flush=True)
        return ""
    if not stages_declare_item_scoped_qa(stages):
        return ""
    if not answer_from_item_detail(item).unanswered:
        return ""
    transition = attachment_transition(item)
    return (
        f"merge refused before the branch landed:\n"
        f"  {public_ref}'s delivery flow {flow_id!r} has an item-scoped QA "
        "stage, so after deployment this item will be asked to prove its own "
        "behaviour on the deployed candidate -- and it has not said what that "
        "proof is, or that it needs none.\n"
        "  Answer it here, while the cases are still editable and the "
        "candidate is still yours. Asked any later, the question arrives with "
        "production already serving the code it was meant to check.\n"
        "  If this item has something to verify once it is live, author a "
        "plan whose cases test this item's acceptance criteria, attach it, "
        "and dry-run it once against your own candidate:\n"
        f"    yoke qa plan create <slug> --project {project_slug} "
        "--environment <env>\n"
        f"    yoke qa plan-cases replace --project {project_slug} "
        "--plan-id <id> --stdin\n"
        f"    {attach_standing_recipe(public_ref, project=project_slug, transition=transition)}\n"
        f"    yoke qa plan run --item {public_ref} "
        f"--transition {transition} "
        "--base-url <your candidate>\n"
        "  That attachment is standing: every future deployment of this item "
        "resolves it, and the deployment stage picks it up on its own, so no "
        "plan choice is needed at the wake.\n"
        "  If it genuinely has nothing to verify once it is live, record "
        "that no post-deploy obligation exists, and why -- that fact is an "
        "answer and is not a waiver; an unanswered item is not an answer:\n"
        f"    {record_no_obligation_recipe(public_ref)}\n"
        f"  {RUN_SCOPED_NOTE}"
    )


__all__ = [
    "DEFAULT_ATTACHMENT_TRANSITION",
    "attachment_transition",
    "completion_flow",
    "flow_stages",
    "has_attached_member_plan",
    "item_scoped_qa_stage_names",
    "missing_item_qa_plan_refusal",
    "stages_declare_item_scoped_qa",
]
