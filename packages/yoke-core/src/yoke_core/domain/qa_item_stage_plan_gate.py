"""Require a member's own item QA plan before its branch lands.

An item whose delivery flow carries an item-scoped QA stage will be asked,
after deployment, to prove its own behaviour on the deployed candidate. If
it reaches that wake with no plan of its own, the only moves left are bad
ones: borrow another item's plan and inherit criteria that were never about
this change, or author a probe under time pressure whose first execution is
against production, after the case has frozen. From there a defect can only
be waived or superseded.

The plan is cheap to write while the item is still in hand, and its cases
are editable right up to the moment one answers. So this refuses the landing
instead, where correcting it costs nothing.

The check reads the flow definition rather than any project's conventions:
an item is only asked for a plan when its own resolved flow declares a QA
stage scoped to items. A flow with no such stage, or none at all, is
unaffected.

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
from collections.abc import Mapping
from typing import Any, Iterable

from yoke_core.domain.qa_deployment_member_attached_plans import (
    DEPLOYMENT_ATTACHMENT_PHASE,
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


def stages_declare_item_scoped_qa(raw: Any) -> bool:
    """True when these stages ask each member to answer for itself."""
    return any(
        str(stage.get("stage_kind") or "") == "qa"
        and str(stage.get("scope") or "") == "item"
        for stage in _stages(raw)
    )


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
    """Relay one flow's stage definitions. Returns ``(stages, error)``."""
    result, error = _relay(
        "deployment_flows.stages", {"flow_id": str(flow_id)}
    )
    if error:
        return None, (
            f"could not read the stages of delivery flow {flow_id!r}, so "
            "whether this item owes its own QA plan cannot be established: "
            f"{error}"
        )
    return (result or {}).get("stages"), ""


def missing_item_qa_plan_refusal(
    item: Mapping[str, Any],
    *,
    public_ref: str,
) -> str:
    """Empty when this item may land, else why it may not and what to do."""
    flow_id = str(item.get("deployment_flow") or "").strip()
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
    stages, error = flow_stages(flow_id)
    if error:
        return error
    if not stages_declare_item_scoped_qa(stages):
        return ""
    if has_attached_member_plan(item.get("qa_plan_attachments") or []):
        return ""
    transition = attachment_transition(item)
    return (
        f"merge refused before the branch landed:\n"
        f"  {public_ref}'s delivery flow {flow_id!r} has an item-scoped QA "
        "stage, so after deployment this item must prove its own behaviour on "
        "the deployed candidate -- but it has no QA plan of its own attached.\n"
        "  Attaching one now, while its cases are still editable, is what "
        "keeps that proof from being written under pressure against "
        "production.\n"
        "  Author a plan whose cases test this item's acceptance criteria, "
        "attach it, and dry-run it once against your own candidate:\n"
        f"    yoke qa plan create <slug> --project {project_slug} "
        "--environment <env>\n"
        f"    yoke qa plan-cases replace --project {project_slug} "
        "--plan-id <id> --stdin\n"
        f"    yoke qa item-plan attach --item {public_ref} "
        f"--project {project_slug} --plan-id <id> "
        f"--transition {transition} "
        f"--qa-phase {DEPLOYMENT_ATTACHMENT_PHASE}\n"
        f"    yoke qa plan run --item {public_ref} "
        f"--transition {transition} "
        "--base-url <your candidate>\n"
        "  The deployment stage then picks that plan up on its own; no plan "
        "choice is needed at the wake."
    )


__all__ = [
    "DEFAULT_ATTACHMENT_TRANSITION",
    "attachment_transition",
    "flow_stages",
    "has_attached_member_plan",
    "missing_item_qa_plan_refusal",
    "stages_declare_item_scoped_qa",
]
