"""Close a member that recorded no post-deploy obligation, without a wake.

The merge close-out is the one path to done. This module is that same
close-out running without a session: the recorded
``post_deploy_no_obligation`` fact, the landing evidence, and the
succeeded completion-flow run already hold every sentence the owner
would write. Auto-close keys on that recorded fact alone. An empty case
set is a member nobody asked and stays held. ``declared_none`` is the
waiver-backed sibling and is out of scope — a waiver auto-closing is a
different proposition from a considered no-obligation auto-closing.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.dash_execution import evaluate_dash_evidence
from yoke_core.domain.post_deploy_verification_answer import answer_for_item
from yoke_core.domain.standalone_item_merge_evidence import CLOSED_OUT_STATUS
from yoke_core.domain.status_claim_bypass_context import status_bypass_override

CLAIM_BYPASS_PREFIX = "merge-close-out:"
STATUS_SOURCE = "merge-close-out"


@dataclass(frozen=True)
class NoObligationCloseOut:
    """Whether this member is the recorded-no-obligation case, and the result.

    ``applies`` is the predicate the wake sites read: false means this is
    not that fact, so the ordinary wake still fires. True means do not
    wake, whether the close-out landed or named why it could not.
    """

    applies: bool
    ok: bool = False
    detail: str = ""


def recorded_no_obligation(conn: Any, item_id: int) -> bool:
    """The authored no-obligation fact, not a waiver and not silence."""
    return answer_for_item(conn, int(item_id)).no_obligation


def close_out_recorded_no_obligation(
    conn: Any, *, item_id: int, public_ref: str
) -> NoObligationCloseOut:
    """Run the merge close-out for one recorded-no-obligation member.

    Evidence must already be on the item from landing; this path never
    invents ``--result`` or ``--verification``. The status write is the
    same ``backlog.execute_update`` the merge close-out already uses,
    with a request-scoped claim bypass so it can run with no session.
    """
    if not recorded_no_obligation(conn, int(item_id)):
        return NoObligationCloseOut(applies=False)
    try:
        return _close_out(conn, item_id=int(item_id), public_ref=str(public_ref))
    except Exception as exc:  # noqa: BLE001 - never reverse the succeeded run
        return NoObligationCloseOut(
            applies=True, ok=False, detail=str(exc) or exc.__class__.__name__
        )


def _close_out(
    conn: Any, *, item_id: int, public_ref: str
) -> NoObligationCloseOut:
    from yoke_core.domain import backlog
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.standalone_item_merge import sync_item_to_github
    from yoke_core.domain.terminal_lane_cleanup import record_terminal_lane_close_out

    named = str(public_ref).strip() or render_item_ref(conn, item_id)
    status = _item_status(conn, item_id)
    if status == CLOSED_OUT_STATUS:
        return NoObligationCloseOut(applies=True, ok=True, detail="already done")
    evidence = evaluate_dash_evidence(conn, item_id)
    if not evidence.satisfied:
        missing = ", ".join(evidence.missing) or "execution_evidence"
        return NoObligationCloseOut(
            applies=True,
            ok=False,
            detail=(
                f"{named} recorded post_deploy_no_obligation but cannot "
                f"auto-close: landing evidence is missing {missing}. Record "
                "it with `yoke merge item` `--result` and `--verification`, "
                "then re-drive the run."
            ),
        )
    captured = io.StringIO()
    with status_bypass_override(
        claim_bypass=f"{CLAIM_BYPASS_PREFIX}{named}",
        status_source=STATUS_SOURCE,
        task_done_verified=False,
    ):
        result = backlog.execute_update(
            item_id,
            "status",
            CLOSED_OUT_STATUS,
            session_id=None,
            out=captured,
            done_nonce_verified=True,
            expected_status=status,
            no_github=True,
        )
    if not result.get("success"):
        return NoObligationCloseOut(
            applies=True,
            ok=False,
            detail=str(result.get("error") or captured.getvalue() or "close-out refused"),
        )
    github_error = sync_item_to_github(item_id)
    envelope: dict[str, Any] = {"warnings": []}
    if github_error:
        envelope["warnings"].append(f"GitHub sync skipped: {github_error}")
    record_terminal_lane_close_out(
        {"id": item_id, "public_ref": named, "claim": None},
        envelope,
        target_status=CLOSED_OUT_STATUS,
        landing_recorded=True,
    )
    _end_previous_claim_holders_if_empty(conn, item_id=item_id)
    print(
        f"{named}: recorded post_deploy_no_obligation; closed out without a wake."
    )
    return NoObligationCloseOut(applies=True, ok=True, detail="closed")


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
                triggered_by="no-obligation-closeout",
            )
        except Exception:  # noqa: BLE001 - best-effort session cleanup
            pass


def _item_status(conn: Any, item_id: int) -> str:
    row = conn.execute(
        "SELECT status FROM items WHERE id=%s", (int(item_id),)
    ).fetchone()
    if row is None:
        return ""
    return str(row["status"] if hasattr(row, "keys") else row[0] or "")


__all__ = [
    "CLAIM_BYPASS_PREFIX",
    "STATUS_SOURCE",
    "NoObligationCloseOut",
    "close_out_recorded_no_obligation",
    "recorded_no_obligation",
]
