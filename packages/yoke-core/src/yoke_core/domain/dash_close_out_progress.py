"""The Progress Log entry a Dash close-out leaves behind."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.gate_satisfier_ladder_catalog import RUNG_AGENT_ATTESTED
from yoke_core.domain.item_activity import touch_item_activity
from yoke_core.domain.item_json_sections import upsert_section
from yoke_core.domain.progress_log import (
    PROGRESS_LOG_ORDERING,
    PROGRESS_LOG_SECTION,
    format_entry,
    join_entry,
)


def append_close_out_progress(
    conn: Any,
    *,
    item_id: int,
    result_summary: str,
    merge_sha: str,
    recorded_at: str,
) -> None:
    """Append the landed outcome once, before the item becomes terminal."""
    marker = (
        f"Merge SHA: `{merge_sha}`"
        if merge_sha
        else f"Satisfier: `{RUNG_AGENT_ATTESTED}`"
    )
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT content FROM item_sections "
        f"WHERE item_id = {placeholder} AND section_name = {placeholder}",
        (int(item_id), PROGRESS_LOG_SECTION),
    ).fetchone()
    existing = str(row[0] or "") if row is not None else ""
    if marker in existing:
        return
    entry = format_entry(
        timestamp=recorded_at,
        headline="Landed",
        body=f"{result_summary}\n\n{marker}",
    )
    upsert_section(
        conn,
        item_id=item_id,
        section=PROGRESS_LOG_SECTION,
        content=join_entry(existing, entry),
        ordering=PROGRESS_LOG_ORDERING,
    )
    touch_item_activity(conn, item_id=item_id)


__all__ = ["append_close_out_progress"]
