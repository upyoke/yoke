"""Which verdicts a QA review may return, derived from its verdict mode.

A stage's ``verdict.mode`` decides whether "undetermined" is an answer at
all: ``agent_only`` has no reviewer to escalate to, so an inconclusive
submission there has nowhere to go and is refused. The two surfaces that
have to agree about this are the dispatch contract, which tells the reviewer
what it may return, and the submission, which refuses what it may not.

They read the list from here so a reviewer is never offered a verdict its
own submission will reject -- an offer that costs a whole review pass to
discover.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_flow_policy import HUMAN_VERDICT_MODES
from yoke_core.domain.qa_constants import UNDETERMINED_VERDICT

#: Verdicts an agent review returns. ``error`` is a runner outcome, not a
#: review's judgment, so it is absent here while staying in the run column's
#: own vocabulary.
CONCLUSIVE_REVIEW_VERDICTS = ("pass", "fail")
ALL_REVIEW_VERDICTS = (*CONCLUSIVE_REVIEW_VERDICTS, UNDETERMINED_VERDICT)


def allowed_review_verdicts(mode: Any) -> tuple[str, ...]:
    """The verdicts a review under *mode* may submit.

    An unrecognized or absent mode keeps the inconclusive answer available:
    the review paths that carry no deployment stage at all -- an item's own
    verification review -- have a default request policy to escalate to, and
    withholding the honest answer there would push a reviewer into guessing
    a conclusive one.
    """
    if str(mode or "") in HUMAN_VERDICT_MODES:
        return ALL_REVIEW_VERDICTS
    if str(mode or "") == "agent_only":
        return CONCLUSIVE_REVIEW_VERDICTS
    return ALL_REVIEW_VERDICTS


def stage_review_verdicts(conn: Any, subject: Any) -> tuple[str, ...]:
    """The verdicts the stage behind one review bundle accepts.

    A bundle whose subject names no deployment stage -- an item's own
    verification review -- has the default request policy to escalate to and
    keeps the full list. A stage whose frozen policy cannot be read keeps it
    too: the submission reads that same authority, so an unreadable stage
    refuses there, where the reader is holding a verdict to record, rather
    than silently narrowing what the reviewer was allowed to conclude.
    """
    from collections.abc import Mapping as _Mapping

    if not isinstance(subject, _Mapping):
        return ALL_REVIEW_VERDICTS
    stage_name = str(subject.get("deployment_stage") or "").strip()
    run_id = str(subject.get("deployment_run_id") or "").strip()
    if not stage_name or not run_id:
        return ALL_REVIEW_VERDICTS
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )

    member = subject.get("deployment_member_item_id")
    try:
        stage_subject = deployment_qa_stage_subject(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            member_item_id=int(member) if member is not None else None,
            require_active=False,
        )
    except (ValueError, KeyError, TypeError):
        return ALL_REVIEW_VERDICTS
    return allowed_review_verdicts(stage_subject["stage"]["verdict"].get("mode"))


def verdict_enum_text(verdicts: tuple[str, ...]) -> str:
    """The enum as a dispatch contract and a ``--help`` line both print it."""
    return "|".join(verdicts)


def inconclusive_verdict_guidance(allowed_verdicts: tuple[str, ...]) -> str:
    """What a reviewer that cannot settle a case may do under this mode.

    An agent-only stage has no reviewer to escalate an unsure verdict to, so
    telling the reviewer to pick undetermined there spends a whole review
    pass to earn a refusal. Naming the conclusive answer instead -- and what
    to put in the rationale -- is the recovery that stage can actually take.
    """
    if UNDETERMINED_VERDICT in allowed_verdicts:
        return (
            "Undetermined spends an owner/operator review and halts the item; "
            "choose it only for attached evidence, and name what could not be "
            "established and why."
        )
    return (
        "This stage decides on the agent verdict alone, so undetermined is not "
        f"submittable here -- return one of {verdict_enum_text(allowed_verdicts)}. "
        "If the supplied evidence cannot settle a case, fail it and name in the "
        "rationale what was missing, which is the answer a re-capture acts on."
    )


__all__ = [
    "ALL_REVIEW_VERDICTS",
    "CONCLUSIVE_REVIEW_VERDICTS",
    "allowed_review_verdicts",
    "inconclusive_verdict_guidance",
    "stage_review_verdicts",
    "verdict_enum_text",
]
