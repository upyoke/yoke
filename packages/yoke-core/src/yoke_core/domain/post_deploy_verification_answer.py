"""Whether an item has answered the post-deploy verification question.

Two surfaces ask the same question about the same item and must agree.

:mod:`yoke_core.domain.qa_item_stage_plan_gate` asks it before the branch
lands, which is the last moment the answer is cheap: the owner still holds
the claim and the lane, and the cases are still editable.

The deployment QA stage asks it after the deploy, when nothing selected
cases for a member. By then the only useful thing left to distinguish is an
item that recorded "nothing to verify, because X" from one nobody ever
asked. Both surfaces reach the same verdict here, so a member cannot be
refused at the merge as unanswered and then read as declared, or the reverse.

Three answers, and the middle one is the whole point: a recorded declaration
is a different artifact from an unanswered question, and only the recorded
one lets a member through with no post-deploy evidence.

A waiver is the declaration, not a new kind of record. ``waived_at``,
``waiver_rationale`` and ``waiver_source`` already carry a reasoned,
attributable decision not to collect evidence, and the done gate already
reads a waived post-deploy row as a cleared blocker. Supersession
deliberately does NOT read as a declaration: a superseded row was taken over
by a replacement that still owes evidence, so it means the item answered,
not that it answered "none".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.qa_deployment_member_attached_plans import (
    DEPLOYMENT_ATTACHMENT_PHASE,
)

#: The item both asked for post-deploy evidence and named what it is.
ANSWERED = "answered"
#: The item recorded that it needs none, and why.
DECLARED_NONE = "declared_none"
#: Nobody has asked, so nobody has answered.
UNANSWERED = "unanswered"

#: ``qa_kind`` a recorded nothing-to-verify declaration carries, so a reader
#: can tell it from a real case whose evidence was waived for its own reason.
DECLARATION_QA_KIND = "post_deploy_not_required"


@dataclass(frozen=True)
class PostDeployAnswer:
    """One item's answer, and the reasons a declaration recorded."""

    verdict: str
    reasons: tuple[str, ...] = ()

    @property
    def answered(self) -> bool:
        return self.verdict == ANSWERED

    @property
    def declared_none(self) -> bool:
        return self.verdict == DECLARED_NONE

    @property
    def unanswered(self) -> bool:
        return self.verdict == UNANSWERED


def _post_deploy(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("qa_phase") or "").strip() == DEPLOYMENT_ATTACHMENT_PHASE
    ]


def classify(
    *,
    attachments: Sequence[Mapping[str, Any]],
    requirements: Sequence[Mapping[str, Any]],
) -> PostDeployAnswer:
    """Classify one item from its own post-deploy attachments and intake rows.

    Both sequences are the item's own records. An admitted deployment copy
    carries ``deployment_member_item_id`` and no ``item_id``, so it never
    reaches here and a run cannot answer the question on the owner's behalf.
    """
    attached = _post_deploy(attachments)
    rows = _post_deploy(requirements)
    if attached or any(not row.get("waived_at") for row in rows):
        return PostDeployAnswer(ANSWERED)
    if rows:
        return PostDeployAnswer(
            DECLARED_NONE,
            tuple(
                reason
                for reason in (
                    str(row.get("waiver_rationale") or "").strip() for row in rows
                )
                if reason
            ),
        )
    return PostDeployAnswer(UNANSWERED)


def answer_from_item_detail(item: Mapping[str, Any]) -> PostDeployAnswer:
    """Classify from a relayed ``items.detail.get`` payload.

    The merge gate is installed-client code with no database of its own, and
    it already holds this payload, so the question costs it no extra read.
    """
    return classify(
        attachments=list(item.get("qa_plan_attachments") or []),
        requirements=list(item.get("qa_requirements") or []),
    )


def answer_for_item(conn: Any, item_id: int) -> PostDeployAnswer:
    """Classify from the control plane, for a caller holding a connection."""
    from yoke_core.domain.db_helpers import query_rows

    attachments = query_rows(
        conn,
        "SELECT qa_phase FROM qa_plan_item_attachments WHERE item_id=%s",
        (int(item_id),),
    )
    requirements = query_rows(
        conn,
        "SELECT qa_phase,waived_at,waiver_rationale FROM qa_requirements "
        "WHERE item_id=%s AND deployment_run_id IS NULL",
        (int(item_id),),
    )
    return classify(attachments=attachments, requirements=requirements)


def member_post_deploy_answer(
    conn: Any, subject: Mapping[str, Any]
) -> PostDeployAnswer:
    """One deployment QA stage subject's answer.

    A run-scoped stage has no member, so no item can have answered for it
    and the stage keeps its own refusal.
    """
    member_item_id = subject.get("member_item_id")
    if member_item_id is None:
        return PostDeployAnswer(UNANSWERED)
    return answer_for_item(conn, int(member_item_id))


def declare_none_recipe(public_ref: str) -> str:
    """The command that records a nothing-to-verify declaration."""
    return (
        f"yoke qa post-deploy declare-none --item {public_ref} "
        '--reason "why this item needs no check once it is deployed"'
    )


def attach_standing_recipe(
    public_ref: str, *, project: str, transition: str
) -> str:
    """The command that attaches a durable per-item post-deploy plan."""
    return (
        f"yoke qa item-plan attach --item {public_ref} --project {project} "
        f"--plan-id <id> --transition {transition} "
        f"--qa-phase {DEPLOYMENT_ATTACHMENT_PHASE}"
    )


#: Why the third choice is named everywhere the other two are, even where it
#: cannot be taken yet. Selecting a plan with ``--plan`` on a running stage
#: and attaching one to the item are both legitimate and mean different
#: things, so a prompt that silently defaulted to either would be teaching
#: one of them as the answer.
RUN_SCOPED_NOTE = (
    "A third choice exists and is not this one: `--plan` on a running "
    "deployment stage binds cases to that single run and writes nothing the "
    "item keeps. It needs a run, so it cannot be made here, and it never "
    "answers this question for the next deployment."
)


def cases_not_selected_refusal(*, member_ref: str = "") -> str:
    """Why a stage naming no cases refuses, and where it should have been asked.

    One text for both refusal sites, so the recovery cannot drift between
    them. It names the earlier surface too: reaching this message at all
    means the question arrived after the deploy rather than before the merge,
    where the owner could still have answered it cheaply.
    """
    subject = member_ref or "PREFIX-N"
    return (
        "deployment QA stage has no pinned cases; select a project QA "
        "plan and retry, naming the same stage (and member, on an "
        "item-scoped stage) this execution runs under: `yoke qa plan run "
        "--deployment-run-id RUN --stage STAGE [--member PREFIX-N] "
        "--plan PLAN --project P`. That selection is run-scoped and dies "
        "with this run. The durable answers belong to the item and are "
        "asked for before it merges: attach a standing plan with `yoke qa "
        "item-plan attach`, or record that it needs none with "
        f"`{declare_none_recipe(subject)}`."
    )


__all__ = [
    "ANSWERED",
    "DECLARATION_QA_KIND",
    "DECLARED_NONE",
    "PostDeployAnswer",
    "RUN_SCOPED_NOTE",
    "UNANSWERED",
    "answer_for_item",
    "answer_from_item_detail",
    "attach_standing_recipe",
    "cases_not_selected_refusal",
    "classify",
    "declare_none_recipe",
    "member_post_deploy_answer",
]
