"""What a release-wait owner owes delivery, and whether anything can wake it.

The close-out block at a release wait used to print the same two promises
for every item: hold the claim and do not end, and re-enter on the
deployment wake. Neither was read from anything. A desktop session — whose
surface Yoke never resumes, because a native resume forks the transcript its
operator is reading — was told a wake would come and sat until the operator
typed; items that had recorded ``post_deploy_no_obligation`` were told to
wait for a re-entry that delivery never needed, since it closed them itself.

Both answers are facts the close-out already holds. What the item owes is
its completion flow's item-scoped QA stages crossed with its own post-deploy
answer — the same two reads the merge gate asked before the branch landed.
Whether this session can be woken is its surface's stopped-session wake
route, read through the one messageability projection every wake route
uses. The block records both facts, and the lines below derive every
promise from them, so nothing is told to wait on a wake that cannot arrive
or for an obligation that does not exist.

Every read is contained: by the time it runs the merge has landed, so a
fact that could not be read is named as unread rather than raised.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_contracts.session_control.capabilities import operator_wake_instruction
from yoke_core.domain.post_deploy_verification_answer import (
    NO_OBLIGATION_QA_KIND,
    answer_from_item_detail,
)
from yoke_core.domain.qa_deployment_member_attached_plans import (
    DEPLOYMENT_ATTACHMENT_PHASE,
)
from yoke_core.domain.qa_item_stage_plan_gate import (
    completion_flow,
    flow_stages,
    item_scoped_qa_stage_names,
)
from yoke_core.domain.session_message_routing import messageability

#: The item has an item-scoped QA stage to answer after the deploy.
OWES_QA = "item_qa"
#: Delivery closes the item itself; nothing will ask its owner for anything.
OWES_NOTHING = "none"
#: What the item owes could not be read, so it is treated as owing.
OWES_UNREAD = "unread"

#: Yoke resumes this surface natively when a stage needs it.
WAKE_NATIVE = "native"
#: Only the person whose window it is may resume it.
WAKE_OPERATOR = "operator"
#: The surface declares no stopped-session wake route at all.
WAKE_NONE = "none"
#: No session row was read, so wakeability is not established.
WAKE_UNREAD = "unread"


def _project_slug(item: Mapping[str, Any]) -> str:
    project = item.get("project")
    if isinstance(project, Mapping):
        return str(project.get("slug") or "")
    return str(project or "")


def _owed_requirement_ids(item: Mapping[str, Any]) -> list[int]:
    """The item's own live post-deploy requirements the stage will admit."""
    owed: list[int] = []
    for row in item.get("qa_requirements") or ():
        if not isinstance(row, Mapping):
            continue
        if str(row.get("qa_phase") or "") != DEPLOYMENT_ATTACHMENT_PHASE:
            continue
        if row.get("retracted_at") or row.get("waived_at"):
            continue
        if row.get("superseded_at") or row.get("qa_kind") == NO_OBLIGATION_QA_KIND:
            continue
        if row.get("id") is not None:
            owed.append(int(row["id"]))
    return owed


def delivery_obligation(item: Mapping[str, Any]) -> dict[str, Any]:
    """What this item owes its delivery, from the flow and its own answer."""
    try:
        flow = completion_flow(item)
        if not flow:
            return {"kind": OWES_UNREAD, "detail": "the item names no completion flow"}
        stages, notice = flow_stages(flow)
        if notice:
            return {"kind": OWES_UNREAD, "detail": notice}
        names = [name for name in item_scoped_qa_stage_names(stages) if name]
        if not names:
            return {
                "kind": OWES_NOTHING,
                "detail": f"flow {flow!r} declares no item-scoped QA stage",
            }
        answer = answer_from_item_detail(item)
        if answer.discharges_without_cases:
            return {
                "kind": OWES_NOTHING,
                "detail": f"the item recorded post-deploy answer {answer.verdict!r}",
            }
        return {
            "kind": OWES_QA,
            "flow": flow,
            "project": _project_slug(item),
            "stages": names,
            "requirement_ids": _owed_requirement_ids(item),
        }
    except Exception as exc:  # noqa: BLE001 - reporting never fails a merge
        return {"kind": OWES_UNREAD, "detail": str(exc)}


def session_wake(session: Any) -> dict[str, Any]:
    """Whether a stopped session on this registered surface can be woken."""
    if not isinstance(session, Mapping) or not session.get("executor_surface"):
        return {"kind": WAKE_UNREAD, "surface": ""}
    surface = str(session["executor_surface"])
    routing = messageability(dict(session), liveness="ended", force_stopped_route=True)
    if str(routing.get("wake_interface") or "none") != "none":
        kind = WAKE_NATIVE
    elif routing.get("wake_authority") == WAKE_OPERATOR:
        kind = WAKE_OPERATOR
    else:
        kind = WAKE_NONE
    return {"kind": kind, "surface": surface}


def stage_recipe(obligation: Mapping[str, Any], public_ref: str) -> str:
    """The scoped run each owed stage credits, one per stage."""
    project = obligation.get("project") or "P"
    return "; ".join(
        f"`yoke watch qa-plan -- --deployment-run-id RUN --stage {stage} "
        f"--member {public_ref} --project {project}`"
        for stage in obligation.get("stages") or ()
    )


def _owes_line(obligation: Mapping[str, Any], public_ref: str) -> str:
    kind = obligation.get("kind")
    if kind == OWES_QA:
        stages = ", ".join(obligation.get("stages") or ())
        ids = ", ".join(str(i) for i in obligation.get("requirement_ids") or ())
        return (
            f"owes delivery: item-scoped QA stage {stages}"
            + (f" (requirements {ids})" if ids else "")
            + f"; the stage credits only {stage_recipe(obligation, public_ref)}"
        )
    if kind == OWES_NOTHING:
        return (
            f"owes delivery: nothing of its own — {obligation.get('detail')}; "
            "delivery closes the item itself and nothing will ask this session "
            "for anything"
        )
    return (
        "owes delivery: not established — "
        f"{obligation.get('detail') or 'the obligation was not read'}; "
        f"treat it as owing until `yoke items detail get {public_ref}` says otherwise"
    )


def _wake_line(wake: Mapping[str, Any], parked: str) -> str:
    kind = wake.get("kind")
    surface = wake.get("surface") or "this"
    if kind == WAKE_NATIVE:
        return f"wake: this {surface} session is woken natively when a stage needs it"
    if kind == WAKE_OPERATOR:
        return (
            f"wake: none will arrive — {operator_wake_instruction(surface)} "
            "A steering seat may ask the operator to re-enter it"
        )
    if kind == WAKE_NONE:
        return (
            f"wake: none will arrive — the {surface} surface declares no "
            "stopped-session wake route, so the operator or a steering seat "
            "must re-enter this session"
        )
    why = parked if parked and parked != "yes" else "the session read named no surface"
    return f"wake: not established ({why})"


def _claim_and_next_lines(
    obligation: Mapping[str, Any], wake: Mapping[str, Any], public_ref: str
) -> list[str]:
    merge = f"yoke merge item {public_ref} --result ... --verification ..."
    recovery = (
        f"a delivery wake comes only for a close-out delivery could not finish, "
        f"and names its recovery (usually `{merge}`)"
    )
    if obligation.get("kind") == OWES_NOTHING:
        return [
            "work claim and lane: kept by this close-out and released by "
            "delivery's own close-out — nothing is required of this session; "
            "report what landed and stop",
            recovery,
        ]
    if obligation.get("kind") == OWES_QA:
        run = f"re-entry runs {stage_recipe(obligation, public_ref)}"
    else:
        run = f"re-entry runs the recipe the stage prints, or `{merge}`"
    if wake.get("kind") == WAKE_NATIVE:
        hold = (
            "work claim and lane: retained through delivery — do not release, "
            "do not end this session; stop and wait for the wake"
        )
    else:
        hold = (
            "work claim and lane: retained through delivery — do not release; "
            "nothing will wake this session, so report that the operator or a "
            "steering seat must re-enter it when the stage opens"
        )
    return [hold, run, recovery]


def awaiting_delivery_lines(record: Mapping[str, Any], public_ref: str) -> list[str]:
    """What a release-wait owner holds, owes, and what re-enters it.

    ``delivery_pending`` leads when the close-out knows which delivery is
    outstanding, so a re-entry that found the deploy still unfinished says
    which run it is waiting on instead of reading as a bare "not closed".
    An unconfirmed park is named rather than softened.
    """
    block = record.get("release_wait")
    block = block if isinstance(block, Mapping) else {}
    parked = str(block.get("parked") or "")
    pending = str(record.get("delivery_pending") or "")
    obligation = block.get("obligation")
    obligation = obligation if isinstance(obligation, Mapping) else {}
    wake = block.get("wake")
    wake = wake if isinstance(wake, Mapping) else {}
    lines = [
        *([f"waiting on: {pending}"] if pending else []),
        _owes_line(obligation, public_ref),
        _wake_line(wake, parked),
        *_claim_and_next_lines(obligation, wake, public_ref),
        f"session parked: {parked or 'not attempted'}"
        + (f" — {block['park_reason']}" if block.get("park_reason") else ""),
    ]
    if parked and not parked.startswith(("yes", "skipped")):
        lines.append(
            "park unconfirmed: stamp it yourself with `yoke sessions touch "
            f'--mode parked --reason "{block.get("park_reason", "")}"` — '
            "declare the wait so wake and recovery routing can find it"
        )
    return lines


__all__ = [
    "OWES_NOTHING",
    "OWES_QA",
    "OWES_UNREAD",
    "WAKE_NATIVE",
    "WAKE_NONE",
    "WAKE_OPERATOR",
    "WAKE_UNREAD",
    "awaiting_delivery_lines",
    "delivery_obligation",
    "session_wake",
    "stage_recipe",
]
