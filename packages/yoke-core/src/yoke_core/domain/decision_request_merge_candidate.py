"""The facts a merge-candidate review is answered from.

A review of a merge candidate is a review of one commit. The request that
carries it therefore has to name that commit in full, plus the branch it
sits on, the base branch it would land on, and the files it would move --
otherwise an approver is asked to clear "the item", and the next commit
inherits a clearance nobody gave it.

The full forty-character hex is required rather than accepted short: an
abbreviation is not an identity, and the whole point of this kind is that a
clearance binds to exactly one head.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any, NoReturn

from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_contract import MERGE_CANDIDATE_REVIEW


KIND = MERGE_CANDIDATE_REVIEW
SUBJECT_TYPE = "item_merge_candidate"
CONTEXT_INVALID = "decision_request_subject_context_invalid"
CONTEXT_RECOVERY = (
    "Create the request through the merge boundary's own candidate-review "
    "gate (`yoke merge-review candidate evaluate`) so the commit, branch, "
    "and touched files come from the lane being landed."
)

REQUIRED_FACTS = (
    "item_id",
    "item_ref",
    "item_title",
    "branch",
    "target",
    "commit_sha",
    "touched_files",
)

_FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")


def _fail(detail: str) -> NoReturn:
    raise ValueError(
        f"{CONTEXT_INVALID}: {KIND} subject_context {detail}. "
        f"Recovery: {CONTEXT_RECOVERY}"
    )


def candidate_subject_key(item_id: int, commit_sha: str) -> str:
    """The typed subject one review answers: this item at this exact head."""
    return f"{int(item_id)}:{str(commit_sha).strip().lower()}"


def require_full_commit_sha(commit_sha: str) -> str:
    """Normalize one candidate head, or refuse the abbreviation."""
    value = str(commit_sha or "").strip().lower()
    if not _FULL_SHA.fullmatch(value):
        _fail(
            "requires a full 40-character lowercase hex commit id; got "
            f"{commit_sha!r}"
        )
    return value


def validate(context: Mapping[str, Any]) -> None:
    """Refuse a candidate review that cannot name what it is reviewing."""
    missing = sorted(set(REQUIRED_FACTS).difference(context))
    if missing:
        _fail("is missing required facts: " + ", ".join(missing))
    item_id = context["item_id"]
    if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id < 1:
        _fail("requires item_id to be a positive integer")
    for field in ("item_ref", "item_title", "branch", "target"):
        if not str(context[field] or "").strip():
            _fail(f"requires a non-empty {field}")
    commit_sha = str(context["commit_sha"] or "").strip()
    if not _FULL_SHA.fullmatch(commit_sha):
        _fail(
            "requires commit_sha to be a full 40-character lowercase hex "
            f"commit id; got {commit_sha!r}"
        )
    touched = context["touched_files"]
    if not isinstance(touched, Sequence) or isinstance(touched, (str, bytes)):
        _fail("requires touched_files to be an array")
    for index, value in enumerate(touched):
        if not str(value or "").strip():
            _fail(f"requires a non-empty touched_files[{index}]")


def candidate_item_id(request: Mapping[str, Any]) -> int:
    """The item one candidate review belongs to, read from its typed key."""
    head = str(request["subject_key"]).split(":", 1)[0]
    if not head.isdigit():
        raise ValueError(
            f"decision request {request['id']} has no verifiable item subject"
        )
    return int(head)


def pending_candidate_requests(conn: Any, item_id: int) -> list[dict[str, Any]]:
    """Open candidate reviews on one item, newest first, whatever head.

    Keyed on the item rather than on one commit because both callers need
    the *other* heads: the gate retires a superseded review as soon as a
    newer head is evaluated, and the posture guard refuses to clear the
    selection while a person is still being asked.
    """
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "decision_requests"):
        return []
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT id, subject_key, kind, project_id, org_id FROM decision_requests "
        f"WHERE kind = {marker} AND subject_type = {marker} "
        f"AND subject_key LIKE {marker} AND status = 'pending' "
        "ORDER BY created_at DESC, id DESC",
        (KIND, SUBJECT_TYPE, f"{int(item_id)}:%"),
    ).fetchall()
    columns = ("id", "subject_key", "kind", "project_id", "org_id")
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in rows
    ]


def subject_ended(
    conn: Any,
    request: Mapping[str, Any],
    _observed_at: str,
) -> tuple[bool, str]:
    """A candidate review ends when its item does, and not before.

    A superseded candidate is retired by the merge gate itself the moment a
    newer head is evaluated, so the only end this has to recognize is the
    item leaving the lifecycle. Anything narrower -- "the lane no longer
    records this commit" -- would call a live review ended on every control
    plane that does not record a lane head.
    """
    from yoke_core.domain.workflow_runtime import (
        ENGINE_TERMINAL_STAGE_IDS,
        load_item_workflow_runtime,
    )

    item_id = candidate_item_id(request)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT status FROM items WHERE id = {marker}",
        (item_id,),
    ).fetchone()
    if row is None:
        return True, f"item {item_id} no longer exists"
    status = str(row[0] if not hasattr(row, "keys") else row["status"])
    runtime = load_item_workflow_runtime(conn, item_id)
    terminal = set(runtime.terminal_stage_ids) | set(ENGINE_TERMINAL_STAGE_IDS)
    if status in terminal:
        return True, f"item {item_id} is at terminal stage {status!r}"
    return False, f"item {item_id} is still at {status!r}"


__all__ = [
    "CONTEXT_INVALID",
    "CONTEXT_RECOVERY",
    "KIND",
    "REQUIRED_FACTS",
    "SUBJECT_TYPE",
    "candidate_item_id",
    "candidate_subject_key",
    "pending_candidate_requests",
    "require_full_commit_sha",
    "subject_ended",
    "validate",
]
