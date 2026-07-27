"""Post-transaction GitHub synchronization for backlog field writes."""

from __future__ import annotations

from typing import Any, TextIO

from yoke_core.domain import backlog_rendering as _rendering
from yoke_core.domain.backlog_queries import LABEL_SYNC_FIELDS


def run_post_db_sync(
    *,
    item_id: int,
    field: str,
    value: Any,
    old_status: str | None,
    out: TextIO,
) -> int:
    """Run GitHub side effects after the authoritative transaction closes."""
    sync_fail_count = 0
    if field == "status" and value in ("done", "cancelled"):
        if not _rendering._close_issue(item_id, out):
            sync_fail_count += 1

    if field in LABEL_SYNC_FIELDS:
        if not _rendering._sync_labels(item_id, out):
            sync_fail_count += 1
            _rendering._record_sync_failure(item_id, "labels", "sync_labels failed")

    if field == "title":
        if not _rendering._sync_title(item_id, out):
            sync_fail_count += 1
            _rendering._record_sync_failure(item_id, "title", "sync_title failed")

    if field in ("frozen", "blocked") and not getattr(
        _rendering, f"_sync_{field}_label"
    )(item_id, value, out):
        sync_fail_count += 1
        _rendering._record_sync_failure(
            item_id,
            f"{field}-label",
            f"sync_{field}_label failed",
        )

    if field == "status" and old_status and old_status != value:
        if not _rendering._post_comment(item_id, old_status, value, out):
            sync_fail_count += 1
            _rendering._record_sync_failure(
                item_id,
                "comment",
                "post_comment failed",
            )
    return sync_fail_count


__all__ = ["run_post_db_sync"]
