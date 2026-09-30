"""The three steps that close one delivery-cleared member.

**Prepare** commits what a close depends on and closes nothing: the
delivery rung the release proved, and the status write's own preflight —
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
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Optional, TextIO

from yoke_core.domain import db_backend
from yoke_core.domain.dash_execution import evaluate_dash_evidence
from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
from yoke_core.domain.gate_satisfier_resolution import record_delivery_evidence_rung
from yoke_core.domain.standalone_item_merge_evidence import CLOSED_OUT_STATUS
from yoke_core.domain.status_claim_bypass_context import status_bypass_override

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

    Landing could not stamp the delivery rung — the release was still
    pending — so it is stamped here, before the evidence read that requires
    it, rather than waking the holder to re-run a merge just to record it.
    Returns ``""`` when the member is ready to stage, or already closed.
    """
    from yoke_core.domain.workflow_status_transition_preflight import (
        prepare_status_transition,
    )

    status = _item_status(conn, int(item_id))
    if status == CLOSED_OUT_STATUS:
        return ""
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
    evidence = evaluate_dash_evidence(conn, int(item_id))
    if not evidence.satisfied:
        missing = ", ".join(evidence.missing) or "execution_evidence"
        return (
            f"landing evidence is missing {missing}. Record it with "
            "`yoke merge item` `--result` and `--verification`, then "
            "re-drive the run"
        )
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


def run_closed_member_effects(
    conn: Any,
    *,
    item_id: int,
    public_ref: str,
    receipt: Any = None,
    out: Optional[TextIO] = None,
) -> str:
    """Run a closed member's post-commit effects; name any that failed.

    Every step is idempotent, so a replay over a member whose effects
    already ran repeats nothing harmful. ``receipt`` is the status write's
    own effect receipt, held only by the pass that committed the close.
    Returns ``""`` when every effect finished.
    """
    from yoke_core.domain.backlog_update_effects import (
        run_post_commit_update_effects,
    )
    from yoke_core.domain.standalone_item_merge import sync_item_to_github
    from yoke_core.domain.terminal_lane_cleanup import record_terminal_lane_close_out

    sink = out if out is not None else io.StringIO()
    try:
        if receipt is not None:
            run_post_commit_update_effects(conn, receipt=receipt, out=sink)
        github_error = sync_item_to_github(int(item_id))
        envelope: dict[str, Any] = {"warnings": []}
        if github_error:
            envelope["warnings"].append(f"GitHub sync skipped: {github_error}")
        record_terminal_lane_close_out(
            {"id": int(item_id), "public_ref": public_ref, "claim": None},
            envelope,
            target_status=CLOSED_OUT_STATUS,
            landing_recorded=True,
        )
        _end_previous_claim_holders_if_empty(conn, item_id=int(item_id))
    except Exception as exc:  # noqa: BLE001 - reported; the close stays committed
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - the failure below is what is reported
            pass
        return str(exc) or exc.__class__.__name__
    if receipt is not None:
        print(
            f"{public_ref}: post-deploy obligations satisfied; closed without a wake."
        )
    return ""


def _end_previous_claim_holders_if_empty(conn: Any, *, item_id: int) -> None:
    """End any previous holding sessions released by the transition if now empty."""
    from yoke_core.domain.sessions_render_end_if_empty import end_session_if_empty
    from yoke_core.domain.work_claim_targets import scope_int_sql

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    item_scope = scope_int_sql(conn, "scope", "item_id")
    epic_scope = scope_int_sql(conn, "scope", "epic_id")
    release_intent = f"item-terminal:{CLOSED_OUT_STATUS}"

    rows = conn.execute(
        "SELECT DISTINCT session_id FROM work_claims "
        f"WHERE release_reason_intent={marker} AND "
        f"((target_kind='item' AND {item_scope}={marker}) OR "
        f"(target_kind='epic_task' AND {epic_scope}={marker}))",
        (release_intent, int(item_id), int(item_id)),
    ).fetchall()

    session_ids = [
        str(row["session_id"] if hasattr(row, "keys") else row[0])
        for row in rows
        if row and (row["session_id"] if hasattr(row, "keys") else row[0])
    ]

    for session_id in sorted(set(session_ids)):
        try:
            end_session_if_empty(
                conn,
                session_id,
                triggered_by="delivery-satisfied-closeout",
            )
        except Exception:  # noqa: BLE001 - best-effort session cleanup
            pass


__all__ = [
    "CLAIM_BYPASS_PREFIX",
    "STATUS_SOURCE",
    "StagedMemberClose",
    "prepare_member_close",
    "run_closed_member_effects",
    "stage_member_close",
]
