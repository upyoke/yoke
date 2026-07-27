"""Batch orchestration for canonical backlog field updates."""

from __future__ import annotations

import sys
from typing import Optional, TextIO

from yoke_core.domain import backlog_rendering as _rendering


def execute_batch_update(
    item_ids: list[int],
    field: str,
    value: str,
    done_nonce_verified: bool = False,
    force: bool = False,
    qa_bypass: bool = False,
    session_id: Optional[str] = None,
    dry_run: bool = False,
    rebuild_board: bool = True,
    out: TextIO = sys.stdout,
) -> dict:
    """Apply one field update across multiple items."""
    from yoke_core.domain.backlog_update_op import execute_update

    updated_count = 0
    for item_id in item_ids:
        result = execute_update(
            item_id=item_id,
            field=field,
            value=value,
            done_nonce_verified=done_nonce_verified,
            force=force,
            qa_bypass=qa_bypass,
            session_id=session_id,
            dry_run=dry_run,
            rebuild_board=False,
            out=out,
        )
        if not result.get("success"):
            result = dict(result)
            result.setdefault("updated_count", updated_count)
            return result
        updated_count += 1

    _rendering._maybe_rebuild_board(rebuild_board, dry_run=dry_run, out=out)
    print(f"Batch updated {updated_count} item(s): {field} → {value}", file=out)
    return {"success": True, "updated_count": updated_count}


__all__ = ["execute_batch_update"]
