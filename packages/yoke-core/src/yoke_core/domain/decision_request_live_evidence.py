"""What a still-pending decision request is refreshed with when it is read.

A frozen snapshot never updates on its own, and a pending gate is exactly
where that hurts: the evidence recorded since it was raised, and the subject
the request is about, both have to be current for a reader to act on them.
This recomputes only those, only while the request is pending, and only into
the copy handed to the caller — the stored row keeps its original snapshot.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.decision_related_evidence import related_screenshot_evidence
from yoke_core.domain.decision_request_contract import (
    DEPLOYMENT_STAGE_APPROVAL,
    LIFECYCLE_TRANSITION_APPROVAL,
    QA_NEEDS_REVIEW,
)
from yoke_core.domain.qa_review_evidence import qa_review_artifact_context


def live_evidence(
    conn: Any,
    kind: str,
    context: dict[str, Any],
    *,
    subject_key: str,
    project_id: Optional[int],
) -> Optional[dict[str, Any]]:
    """Recompute evidence live for a still-pending request.

    A frozen snapshot never updates on its own; this reruns the same
    resolution against the request's frozen subject, so a pending read sees
    evidence recorded since -- the stored row, and every resolved or
    withdrawn read, keep the original snapshot untouched. ``subject_key``/
    ``project_id`` are the row's own typed identity, set once and never
    rewritten -- matching ``run_id``/``requirement_id`` to each other alone
    doesn't prove either agrees with the request this row actually is.
    """
    if kind == LIFECYCLE_TRANSITION_APPROVAL:
        item_id = context.get("item_id")
        if item_id is None:
            return None
        changes = context.get("branch_changes") or {}
        return {
            "evidence": related_screenshot_evidence(
                conn, item_id=int(item_id), expected_revision=changes.get("commit_sha")
            )
        }
    if kind == DEPLOYMENT_STAGE_APPROVAL:
        run_id = context.get("run_id")
        if run_id is None:
            return None
        shipping = context.get("shipping") or {}
        return {
            "evidence": related_screenshot_evidence(
                conn,
                deployment_run_id=str(run_id),
                expected_revision=shipping.get("release_lineage"),
            )
        }
    if kind == QA_NEEDS_REVIEW:
        requirement_id = context.get("requirement_id")
        run_id = context.get("run_id")
        if requirement_id is None or run_id is None:
            return None
        if str(int(requirement_id)) != str(subject_key).strip():
            return None
        live = dict(
            qa_review_artifact_context(
                conn,
                requirement_id=int(requirement_id),
                run_id=int(run_id),
                expected_project_id=int(project_id) if project_id is not None else None,
            )
        )
        # The subject is refreshed with the evidence, from the requirement's
        # own row. A reader that has to address this review by the item it is
        # about — a release card listing what it carries — cannot recover
        # that from a snapshot frozen before the association was recorded,
        # and would silently drop the request instead.
        from yoke_core.domain.qa_review_requirement_facts import (
            requirement_facts,
            review_subject,
        )

        from yoke_core.domain.db_backend import operational_error_types

        try:
            live["subject"] = review_subject(
                requirement_facts(conn, int(requirement_id))
            )
        except (LookupError, ValueError, *operational_error_types(conn)):
            # The stored snapshot still names the subject, so a requirement
            # this connection cannot read is a refresh that did not happen
            # rather than a request that cannot be answered.
            pass
        return live
    return None


__all__ = ["live_evidence"]
