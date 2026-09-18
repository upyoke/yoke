"""Hold a landing until a person has cleared the exact commit it carries.

An item whose posture selects ``merge_candidate_review`` may not land until
an authorized reviewer has approved the head the merge would take. The
clearance is an ordinary decision request, bound to ``<item_id>:<sha>``, so
every mechanism that already exists around a human gate -- the Inbox, the
role authorities, the approval policy, the audit events -- applies here
without a second implementation.

Binding to the commit is what makes the guarantee hold: a new commit is a
different subject, so it has no clearance, and the approval given to the
previous head can never be inherited. The same property retires the old
review -- an open request for a head nobody will land now is a question
asked of a person for no reason, so it is withdrawn the moment a newer head
is evaluated.

The evaluation runs where the control plane is, not where git is: the merge
boundary holds the repository and asks this through the registered
``merge_review.candidate.evaluate`` function, so an https relay and a local
Postgres universe answer identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from yoke_core.domain.approval_gate import (
    role_authorities_for,
    verdict_from_request_history,
    withdraw_stale_pending_request,
)
from yoke_core.domain.dash_posture_read import posture as read_posture
from yoke_core.domain.decision_request_merge_candidate import (
    KIND,
    SUBJECT_TYPE,
    candidate_subject_key,
    pending_candidate_requests,
    require_full_commit_sha,
)
from yoke_core.domain.decision_requests import (
    create_decision_request,
    list_subject_requests,
)
from yoke_core.domain.lifecycle_approval_context import load_lifecycle_item
from yoke_core.domain.project_identity import render_item_ref

#: The posture key an item selects to require this review.
POSTURE_KEY = "merge_candidate_review"

_WAITING = "a reviewer has not yet cleared this candidate"
_APPROVED = "this candidate was cleared for landing"
_REJECTED = "this candidate was rejected"
_NOT_SELECTED = (
    f"{POSTURE_KEY} posture is not selected on this item, so no candidate "
    "review is required"
)


@dataclass(frozen=True)
class CandidateReviewVerdict:
    """What one candidate's review says about landing it."""

    required: bool
    satisfied: bool
    item_id: int
    commit_sha: str
    reason: str
    request_id: Optional[int] = None
    request_status: str = ""
    resolution_action: Optional[str] = None
    superseded_request_ids: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "satisfied": self.satisfied,
            "item_id": self.item_id,
            "commit_sha": self.commit_sha,
            "reason": self.reason,
            "request_id": self.request_id,
            "request_status": self.request_status,
            "resolution_action": self.resolution_action,
            "superseded_request_ids": list(self.superseded_request_ids),
        }


def _item_ref(conn: Any, item: dict[str, Any]) -> str:
    """Name the item the way every operator-facing surface names it."""
    return render_item_ref(conn, int(item["id"]))


def _retire_superseded(
    conn: Any,
    *,
    item_id: int,
    subject_key: str,
    commit_sha: str,
    session_id: str,
) -> tuple[int, ...]:
    """Withdraw open reviews of heads this candidate replaced.

    A review of a head nobody will land is a question asked of a person for
    no reason. Retiring it here rather than waiting for the item to end is
    what keeps one open review per item instead of one per abandoned head.
    """
    retired: list[int] = []
    for row in pending_candidate_requests(conn, item_id):
        if str(row["subject_key"]) == subject_key:
            continue
        withdraw_stale_pending_request(
            conn,
            row,
            session_id=session_id,
            reason=f"superseded by candidate {commit_sha}",
        )
        retired.append(int(row["id"]))
    return tuple(retired)


def evaluate_candidate_review(
    conn: Any,
    *,
    item_id: int,
    commit_sha: str,
    branch: str,
    target: str,
    touched_files: Sequence[str] = (),
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
) -> CandidateReviewVerdict:
    """Fail closed until this exact head carries an authorized approval."""
    item = load_lifecycle_item(conn, int(item_id))
    sha = require_full_commit_sha(commit_sha)
    if read_posture(item).get(POSTURE_KEY) is not True:
        return CandidateReviewVerdict(
            required=False,
            satisfied=True,
            item_id=int(item_id),
            commit_sha=sha,
            reason=_NOT_SELECTED,
        )
    subject_key = candidate_subject_key(int(item_id), sha)
    item_ref = _item_ref(conn, item)
    superseded = _retire_superseded(
        conn,
        item_id=int(item_id),
        subject_key=subject_key,
        commit_sha=sha,
        session_id=session_id,
    )
    verdict = verdict_from_request_history(
        conn,
        list_subject_requests(conn, SUBJECT_TYPE, subject_key),
        # The commit is in the subject key, so history for this key is about
        # this candidate and nothing else; there is no second snapshot to
        # compare and no stale-pending case to withdraw here.
        snapshot_matches=lambda _request: True,
        session_id=session_id,
        stale_reason="candidate review snapshots cannot go stale",
        reraise_after_reject=False,
        waiting_reason=_WAITING,
        approved_reason=_APPROVED,
        rejected_reason=_REJECTED,
    )
    if verdict is not None:
        conn.commit()
        return CandidateReviewVerdict(
            required=True,
            satisfied=verdict.satisfied,
            item_id=int(item_id),
            commit_sha=sha,
            reason=verdict.reason,
            request_id=verdict.request_id,
            request_status=verdict.request_status,
            resolution_action=verdict.resolution_action,
            superseded_request_ids=superseded,
        )
    org_id = item.get("org_id")
    role_names = ["owner", "operator"]
    if org_id is not None:
        role_names.append("admin")
    request, _created = create_decision_request(
        conn,
        kind=KIND,
        subject_type=SUBJECT_TYPE,
        subject_key=subject_key,
        project_id=int(item["project_id"]),
        originator_actor_id=originator_actor_id,
        role_authorities=role_authorities_for(
            project_id=int(item["project_id"]),
            org_id=org_id,
            role_names=role_names,
        ),
        subject_context={
            "item_id": int(item_id),
            "item_ref": item_ref,
            "item_title": str(item["title"]),
            "branch": str(branch),
            "target": str(target),
            "commit_sha": sha,
            "touched_files": [str(value) for value in touched_files],
        },
        session_id=session_id,
    )
    return CandidateReviewVerdict(
        required=True,
        satisfied=False,
        item_id=int(item_id),
        commit_sha=sha,
        reason=_WAITING,
        request_id=int(request["id"]),
        request_status="pending",
        superseded_request_ids=superseded,
    )


__all__ = [
    "CandidateReviewVerdict",
    "POSTURE_KEY",
    "evaluate_candidate_review",
]
