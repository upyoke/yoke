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
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_deployment_member_attached_plans import (
    DEPLOYMENT_ATTACHMENT_PHASE,
    attached_member_plan_ids,
)


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


def flow_has_item_scoped_qa_stage(conn: Any, flow_id: str) -> bool:
    """True when this flow asks each member to answer for itself."""
    if not str(flow_id or "").strip():
        return False
    rows = query_rows(
        conn, "SELECT stages FROM deployment_flows WHERE id=%s", (str(flow_id),)
    )
    if not rows:
        return False
    return any(
        str(stage.get("stage_kind") or "") == "qa"
        and str(stage.get("scope") or "") == "item"
        for stage in _stages(rows[0]["stages"])
    )


def missing_item_qa_plan_refusal(
    conn: Any,
    *,
    item_id: int,
    public_ref: str,
    project: str,
    flow_id: str,
) -> str:
    """Empty when this item may land, else why it may not and what to do."""
    if not flow_has_item_scoped_qa_stage(conn, flow_id):
        return ""
    if attached_member_plan_ids(conn, member_item_id=int(item_id)):
        return ""
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
        f"    yoke qa plan create <slug> --project {project} "
        "--environment <env>\n"
        f"    yoke qa plan-cases replace --project {project} "
        "--plan-id <id> --stdin\n"
        f"    yoke qa item-plan attach --item {public_ref} --project {project} "
        f"--plan-id <id> --transition reviewing-implementation "
        f"--qa-phase {DEPLOYMENT_ATTACHMENT_PHASE}\n"
        f"    yoke qa plan run --item {public_ref} "
        "--transition reviewing-implementation --base-url <your candidate>\n"
        "  The deployment stage then picks that plan up on its own; no plan "
        "choice is needed at the wake."
    )


__all__ = ["flow_has_item_scoped_qa_stage", "missing_item_qa_plan_refusal"]
