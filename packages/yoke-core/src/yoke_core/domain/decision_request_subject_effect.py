"""Carry a resolved decision into the subject it was gating, keyed by kind.

Answering a request and acting on the answer are two different acts, and the
second differs entirely by kind: a QA review writes its verdict onto the
requirement, a deployment stage decision reaches a run. Both halves of that
acting live here -- the in-transaction effect on the subject's own state, and
the after-commit notification to whoever was waiting -- keyed by
``decision_requests.kind`` exactly the way
:mod:`yoke_core.domain.decision_request_subject_state` keys its withdrawal
checks.

A kind with no entry has no subject effect, and that is a real answer rather
than a gap: for those kinds the request resolving IS the whole outcome, and
whoever asked reads the resolution itself.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_core.domain.decision_request_contract import DEPLOYMENT_STAGE_APPROVAL

QA_NEEDS_REVIEW_KIND = "qa_needs_review"

#: Applies the resolved answer to the subject, inside the resolution's own
#: transaction so the subject cannot be left disagreeing with the decision.
SubjectEffect = Callable[..., None]

#: Tells whoever was waiting, after the resolution committed. ``None`` means
#: nobody was owed a notice; ``""`` means somebody was and none could be
#: reached, which is the only case worth reporting.
SubjectNotice = Callable[..., Optional[str]]

#: Names the subject in the degraded-delivery reports below.
SubjectLabel = Callable[[dict[str, Any]], str]


def _qa_requirement_label(request: dict[str, Any]) -> str:
    return f"QA requirement {request['subject_key']}"


def _apply_qa_review(
    conn: Any,
    request: dict[str, Any],
    *,
    action: str,
    actor_id: int,
    note: Optional[str],
    stamp: str,
    session_id: str,
) -> None:
    from yoke_core.domain.qa_review_requests import apply_qa_review_resolution
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "qa_requirements"):
        return
    context = request.get("subject_context") or {}
    try:
        reviewed_run_id = int(context.get("run_id") or 0) or None
    except (TypeError, ValueError):
        reviewed_run_id = None
    apply_qa_review_resolution(
        conn,
        requirement_id=int(request["subject_key"]),
        action=action,
        actor_id=actor_id,
        note=note,
        resolved_at=stamp,
        reviewed_run_id=reviewed_run_id,
    )


def _notify_qa_review(
    conn: Any,
    request: dict[str, Any],
    *,
    action: str,
    note: Optional[str],
) -> Optional[str]:
    from yoke_core.domain.deployment_qa_verdict_notice import (
        notify_deployment_qa_verdict,
    )

    return notify_deployment_qa_verdict(
        conn,
        requirement_id=int(request["subject_key"]),
        action=action,
        note=note or "",
    )


def _deployment_stage_label(request: dict[str, Any]) -> str:
    from yoke_core.domain.deployment_stage_decision_effect import stage_subject_label

    return stage_subject_label(request)


def _apply_deployment_stage(
    conn: Any,
    request: dict[str, Any],
    *,
    action: str,
    actor_id: int,
    note: Optional[str],
    stamp: str,
    session_id: str,
) -> None:
    from yoke_core.domain.deployment_stage_decision_effect import (
        apply_deployment_stage_decision,
    )

    apply_deployment_stage_decision(
        conn,
        request,
        action=action,
        actor_id=actor_id,
        note=note,
        stamp=stamp,
        session_id=session_id,
    )


def _notify_deployment_stage(
    conn: Any,
    request: dict[str, Any],
    *,
    action: str,
    note: Optional[str],
) -> Optional[str]:
    from yoke_core.domain.deployment_stage_decision_effect import (
        notify_deployment_stage_decision,
    )

    return notify_deployment_stage_decision(conn, request, action=action, note=note)


_SUBJECT_EFFECTS: dict[str, SubjectEffect] = {
    QA_NEEDS_REVIEW_KIND: _apply_qa_review,
    DEPLOYMENT_STAGE_APPROVAL: _apply_deployment_stage,
}

_SUBJECT_NOTICES: dict[str, tuple[SubjectNotice, SubjectLabel]] = {
    QA_NEEDS_REVIEW_KIND: (_notify_qa_review, _qa_requirement_label),
    DEPLOYMENT_STAGE_APPROVAL: (_notify_deployment_stage, _deployment_stage_label),
}


def apply_subject_resolution(
    conn: Any,
    request: dict[str, Any],
    *,
    action: str,
    actor_id: int,
    note: Optional[str],
    stamp: str,
    session_id: str = "",
) -> None:
    """Carry the resolved decision into the subject the request was gating."""
    effect = _SUBJECT_EFFECTS.get(str(request["kind"]))
    if effect is None:
        return
    effect(
        conn,
        request,
        action=action,
        actor_id=actor_id,
        note=note,
        stamp=stamp,
        session_id=session_id,
    )


def notify_subject_resolution(
    conn: Any,
    request: dict[str, Any],
    *,
    action: str,
    note: Optional[str],
) -> None:
    """Tell whoever was waiting on this decision what it was.

    Called after the resolution has committed, and deliberately: the verdict
    is the durable outcome and a notification hiccup must not endanger it. A
    failure degrades to a printed warning naming the subject, because the
    decision stands either way and the recipient can still read it.
    """
    entry = _SUBJECT_NOTICES.get(str(request["kind"]))
    if entry is None:
        return
    notifier, label = entry
    subject = label(request)
    try:
        delivery = notifier(conn, request, action=action, note=note)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - degrade, never undo the verdict
        conn.rollback()
        print(f"Warning: could not reach whoever was waiting on {subject}: {exc}")
        return
    if delivery == "":
        print(
            f"{subject} was resolved with nobody addressable to tell. "
            "Staff it manually."
        )


__all__ = [
    "apply_subject_resolution",
    "notify_subject_resolution",
]
