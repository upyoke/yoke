"""The execution-evidence record behind a standalone merge's close-out.

Writing the record and reading it back belong together, because the merge
result envelope answers ``evidence_recorded`` from the record's state
rather than from the outcome of one write attempt. Those are different
answers whenever a call succeeds on retry: a transient credential refusal
on a relayed write reports a failure after the row already exists, and a
landing re-entered after its close-out completed finds the work claim
released and the item terminal. Both cases reported a failed merge over a
finished one, which sends an operator to repair state that is already
correct.

So the envelope asks the record. The write path reports its own error for
the caller to name, and the caller confirms against
:func:`recorded` before believing it; a re-entry against an item that has
already closed out converges on :func:`closed_out_envelope`, whose facts
come from the persisted record rather than from a merge this process did
not perform.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION

# The status a standalone item reaches once its close-out has run. An item
# short of it has work left, so a claim refusal there is a real refusal.
CLOSED_OUT_STATUS = "done"


def _relay_error(response: Any, fallback: str) -> str:
    error = getattr(response, "error", None)
    return getattr(error, "message", None) or fallback if error else fallback


def record(
    *,
    item_id: int,
    outcome: Any,
    result_summary: str,
    verification_summary: str,
    verification_status: str,
    no_changes: bool,
    tree_root: str,
) -> str:
    """Write the item's execution evidence; empty string on success."""
    response = call_dispatcher(
        function_id="direct_workflow.dash.evidence",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "result_summary": result_summary,
            "verification_summary": verification_summary,
            "verification_status": verification_status,
            "commit_sha": outcome.commit_sha,
            "merge_sha": outcome.merge_sha,
            "touched_files": list(outcome.touched_files),
            "no_changes": no_changes,
            # The lane's own tip is what verification covered; the merge
            # commit belongs to the base branch, not to the tree tested.
            "tree_root": tree_root,
            "tree_head_sha": outcome.commit_sha,
        },
    )
    if response.success:
        return ""
    return _relay_error(response, "evidence write failed")


def recorded(item_id: int) -> Optional[dict[str, Any]]:
    """The item's persisted execution evidence, or ``None`` when absent."""
    response = call_dispatcher(
        function_id="items.section.get",
        target=TargetRef(
            kind="section", item_id=item_id,
            section_name=DASH_EVIDENCE_SECTION,
        ),
        payload={},
    )
    if not getattr(response, "success", False):
        return None
    result = getattr(response, "result", None) or {}
    if not result.get("found"):
        return None
    try:
        parsed = json.loads(str(result.get("content") or ""))
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def recorded_covers_merge(item_id: int, merge_sha: str) -> bool:
    """Whether the persisted record answers for ``merge_sha``.

    A record left by some earlier landing is not evidence for this one, so
    the merge identity has to match before a refused write is forgiven.
    """
    row = recorded(item_id)
    if row is None:
        return False
    return str(row.get("merge_sha") or "") == str(merge_sha or "")


def closed_out_envelope(
    item: dict[str, Any],
    *,
    item_ref: str,
    branch: str,
    claim_note: str,
) -> Optional[dict[str, Any]]:
    """The finished landing this item already recorded, if there is one.

    Returns ``None`` when the item still has close-out work, so a claim
    refusal on it stays a refusal.
    """
    if str(item.get("status") or "") != CLOSED_OUT_STATUS:
        return None
    evidence = recorded(int(item["id"]))
    if evidence is None:
        return None
    return {
        "ok": True,
        "item_id": int(item["id"]),
        "item_ref": item_ref,
        "branch": branch,
        "already_merged": True,
        "commit_sha": str(evidence.get("commit_sha") or ""),
        "merge_sha": str(evidence.get("merge_sha") or ""),
        "touched_files": list(evidence.get("touched_files") or []),
        # No ``published`` or ``target`` key: neither is a fact this record
        # carries, and inventing one would be the same class of dishonesty
        # this convergence exists to remove.
        "evidence_recorded": True,
        "status": str(item.get("status") or ""),
        "warnings": [
            f"{item_ref} already closed out: evidence recorded at "
            f"{evidence.get('recorded_at') or 'an earlier attempt'} and the "
            f"item is {CLOSED_OUT_STATUS} ({claim_note})"
        ],
    }


__all__ = [
    "CLOSED_OUT_STATUS",
    "closed_out_envelope",
    "record",
    "recorded",
    "recorded_covers_merge",
]
