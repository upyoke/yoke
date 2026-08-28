"""Bounded retry wrapper for canonical backlog item updates."""

from __future__ import annotations

import sys
from typing import Optional, TextIO

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
    rebuild_board: bool = True,
    no_github: bool = False,
    out: TextIO = sys.stdout,
    expected_status: Optional[str] = None,
    originator_actor_id: Optional[int] = None,
) -> dict:
    """Repeat the complete status preflight and update once after drift."""
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
                rebuild_board=rebuild_board,
                no_github=no_github,
                out=out,
                expected_status=expected_status,
                originator_actor_id=originator_actor_id,
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
