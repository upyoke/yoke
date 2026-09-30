"""Bounded retry wrapper for canonical backlog item updates."""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_status_write_precondition import (
    WORKFLOW_STATUS_PRECONDITION_FAILED,
)
from yoke_core.domain.backlog_update_op import _execute_update_once
from yoke_core.domain.blitz_document_archive import BlitzDocumentArchiveError


def execute_update(
    item_id: int,
    field: str,
    value: str,
    resolution: Optional[str] = None,
    done_nonce_verified: bool = False,
    force: bool = False,
    qa_bypass: bool = False,
    session_id: Optional[str] = None,
    dry_run: bool = False,
    no_github: bool = False,
    out: TextIO = sys.stdout,
    expected_status: Optional[str] = None,
    originator_actor_id: Optional[int] = None,
    conn: Any = None,
) -> dict:
    """Repeat the complete status preflight and update once after drift.

    ``conn`` runs the update inside the caller's open transaction: nothing
    is committed, rolled back, or synced to GitHub here, and success returns
    the ``effect_receipt`` the caller runs through
    ``backlog_update_effects.run_post_commit_update_effects`` once it has
    committed. A refusal leaves the caller to roll back.
    """
    if conn is not None and dry_run:
        raise ValueError(
            "dry_run previews and rolls back on its own connection; "
            "it cannot run inside a caller's transaction"
        )
    if field == "status" and value == "cancelled":
        from yoke_core.domain.backlog_cancellation import normalize_cancellation_reason

        resolution, reason_error = normalize_cancellation_reason(resolution)
        if reason_error:
            return {
                "success": False,
                "error": reason_error,
                "error_code": "VALIDATION_ERROR",
            }
    result: dict = {}
    for _attempt in range(2):
        try:
            result = _execute_update_once(
                item_id=item_id,
                field=field,
                value=value,
                resolution=resolution,
                done_nonce_verified=done_nonce_verified,
                force=force,
                qa_bypass=qa_bypass,
                session_id=session_id,
                dry_run=dry_run,
                no_github=no_github,
                out=out,
                expected_status=expected_status,
                originator_actor_id=originator_actor_id,
                conn=conn,
            )
        except BlitzDocumentArchiveError as exc:
            return {
                "success": False,
                "error": str(exc),
                "error_code": exc.code,
            }
        if result.get("error_code") != WORKFLOW_STATUS_PRECONDITION_FAILED:
            return result
    return result


__all__ = ["execute_update"]
