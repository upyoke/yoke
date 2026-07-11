"""Public two-unit wrappers for committed migration manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yoke_core.domain import db_helpers
from yoke_core.domain.migration_apply_contract import LiveApplyResult, RehearseResult
from yoke_core.domain.migration_apply_live import _live_apply_inner
from yoke_core.domain.migration_apply_manifest import resolve_manifest_subject
from yoke_core.domain.migration_apply_rehearse import _rehearse_inner


def rehearse_manifest(
    manifest_path: Path,
    *,
    worktree_path: Path,
    session_id: Optional[str] = None,
    control_db_path: Optional[str] = None,
) -> RehearseResult:
    """Run rehearsal from a committed manifest without creating an item."""

    control_conn = db_helpers.connect(control_db_path)
    try:
        subject = resolve_manifest_subject(
            control_conn,
            manifest_path=manifest_path,
            worktree_path=worktree_path,
        )
        return _rehearse_inner(
            control_conn,
            item_id=None,
            session_id=session_id,
            worktree_path=Path(worktree_path).resolve(),
            subject=subject,
        )
    finally:
        control_conn.close()


def live_apply_manifest(
    manifest_path: Path,
    *,
    worktree_path: Path,
    session_id: Optional[str] = None,
    control_db_path: Optional[str] = None,
) -> LiveApplyResult:
    """Run live apply from the exact committed manifest rehearsed earlier."""

    control_conn = db_helpers.connect(control_db_path)
    try:
        subject = resolve_manifest_subject(
            control_conn,
            manifest_path=manifest_path,
            worktree_path=worktree_path,
        )
        return _live_apply_inner(
            control_conn,
            item_id=None,
            session_id=session_id or "live-apply-manifest",
            worktree_path=Path(worktree_path).resolve(),
            subject=subject,
        )
    finally:
        control_conn.close()


__all__ = ["live_apply_manifest", "rehearse_manifest"]
