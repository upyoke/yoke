"""The three steps that close one delivery-cleared member.

**Prepare** commits what a close depends on and closes nothing: the
workflow-owned delivery evidence, and the status write's own preflight —
its materialized QA and any approval request it has to open. Each is
idempotent, and the done gates read them on their own connections, so they
are committed before any member is written.

**Stage** writes the member's terminal status and claim release into the
caller's open transaction through the ordinary status write, run on the
caller's connection. The caller commits one member, or a run's every member
together.

**Effects** run after that commit and are idempotent: the status write's
post-commit receipt, GitHub sync, terminal lane cleanup, and ending holder
sessions the release left empty. A failure here never reopens the member.
They live in :mod:`delivery_member_close_effects`, which never holds a
transaction across their file-system work.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.dash_execution import evaluate_dash_evidence
from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
from yoke_core.domain.floor_attestation import DIRECT_EVIDENCE_WORKFLOWS
from yoke_core.domain.gate_satisfier_resolution import record_delivery_evidence_rung
from yoke_core.domain.standalone_item_merge_evidence import CLOSED_OUT_STATUS
from yoke_core.domain.status_claim_bypass_context import status_bypass_override
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

CLAIM_BYPASS_PREFIX = "merge-close-out:"
STATUS_SOURCE = "merge-close-out"


@dataclass(frozen=True)
class StagedMemberClose:
    """One member's close, written into the caller's open transaction.

    ``refusal`` names why it could not be written; the caller rolls back.
    ``receipt`` carries the status write's post-commit effects, and is
    ``None`` when the member was already closed and nothing was written.
    """

    item_id: int
    public_ref: str
    refusal: str = ""
    receipt: Any = None


def _item_status(conn: Any, item_id: int) -> str:
    row = conn.execute(
        "SELECT status FROM items WHERE id=%s", (int(item_id),)
    ).fetchone()
    if row is None:
        return ""
    return str(row["status"] if hasattr(row, "keys") else row[0] or "")


def _bypass(public_ref: str) -> Any:
    """The request-scoped claim bypass a session-less close-out runs under."""
    return status_bypass_override(
        claim_bypass=f"{CLAIM_BYPASS_PREFIX}{public_ref}",
        status_source=STATUS_SOURCE,
        task_done_verified=False,
    )


def prepare_member_close(conn: Any, *, item_id: int, public_ref: str) -> str:
    """Commit this member's close prerequisites; return why it cannot close.

    Direct-evidence workflows stamp the delivery rung landing could not
    record while the release was pending. Every member then runs its own
    pinned workflow's status preflight; other workflows own other evidence.
    Returns ``""`` when the member is ready to stage, or already closed.
    """
    from yoke_core.domain.workflow_status_transition_preflight import (
        prepare_status_transition,
    )

    status = _item_status(conn, int(item_id))
    if status == CLOSED_OUT_STATUS:
        return ""
    runtime = load_item_workflow_runtime(conn, int(item_id))
    if runtime.workflow_id in DIRECT_EVIDENCE_WORKFLOWS:
        try:
            record_delivery_evidence_rung(
                conn,
                item_id=int(item_id),
                merge_recorded=bool(item_merge_identity(conn, int(item_id))),
            )
        except ValueError as exc:
            conn.rollback()
            return f"its delivery evidence could not be stamped: {exc}"
        conn.commit()
        if refusal := member_close_evidence_refusal(conn, item_id=int(item_id)):
            return refusal
    with _bypass(public_ref):
        preflight = prepare_status_transition(
            conn,
            item_id=int(item_id),
            target_status=CLOSED_OUT_STATUS,
            originator_actor_id=None,
            session_id="",
            expected_status=status,
        )
    if preflight.failure is not None:
        return str(preflight.failure.get("error") or "close-out preflight refused")
    return ""


def member_close_evidence_refusal(
    conn: Any, *, item_id: int, delivery_pending: bool = False
) -> str:
    """Read the same execution evidence preparation requires, without stamping.

    Preparation derives the delivery rung before checking evidence. A preview
    may omit that one pending stamp only; no authored evidence is invented.
    """
    from yoke_core.domain.gate_satisfier_resolution import OBLIGATION_DELIVERY_EVIDENCE

    runtime = load_item_workflow_runtime(conn, item_id)
    if runtime.workflow_id not in DIRECT_EVIDENCE_WORKFLOWS:
        return ""
    evidence = evaluate_dash_evidence(conn, item_id)
    missing = tuple(
        name
        for name in evidence.missing
        if not (delivery_pending and name == OBLIGATION_DELIVERY_EVIDENCE)
    )
    if not missing:
        return ""
    return (
        f"landing evidence is missing {', '.join(missing)}. Record it with "
        "`yoke merge item` `--result` and `--verification`, then re-drive the run"
    )


def stage_member_close(
    conn: Any, *, item_id: int, public_ref: str
) -> StagedMemberClose:
    """Write this member's terminal status and claim release, uncommitted.

    The status write is the same ``backlog.execute_update`` the merge
    close-out uses — the same preflight, gates, and terminal effects — run
    on the caller's connection so it commits with the caller's transaction.
    Call :func:`prepare_member_close` first and commit its prerequisites.
    """
    from yoke_core.domain import backlog

    status = _item_status(conn, int(item_id))
    if status == CLOSED_OUT_STATUS:
        return StagedMemberClose(item_id=int(item_id), public_ref=public_ref)
    captured = io.StringIO()
    with _bypass(public_ref):
        result = backlog.execute_update(
            int(item_id),
            "status",
            CLOSED_OUT_STATUS,
            session_id=None,
            out=captured,
            done_nonce_verified=True,
            expected_status=status,
            no_github=True,
            conn=conn,
        )
    if not result.get("success"):
        return StagedMemberClose(
            item_id=int(item_id),
            public_ref=public_ref,
            refusal=str(
                result.get("error") or captured.getvalue() or "close-out refused"
            ),
        )
    return StagedMemberClose(
        item_id=int(item_id), public_ref=public_ref, receipt=result["effect_receipt"]
    )


__all__ = [
    "CLAIM_BYPASS_PREFIX",
    "STATUS_SOURCE",
    "StagedMemberClose",
    "prepare_member_close",
    "member_close_evidence_refusal",
    "stage_member_close",
]
