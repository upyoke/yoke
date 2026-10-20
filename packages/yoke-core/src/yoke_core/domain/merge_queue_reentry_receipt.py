"""Keep successful automatic queue re-entry evidence beyond observation refresh."""

from __future__ import annotations

import json

from yoke_contracts.timestamps import format_instant
from yoke_core.domain import db_backend
from yoke_core.domain.item_json_sections import upsert_json_section

REENTRY_SECTION = "Queue re-entry receipts"


def record_reentry(conn, item_id, pr_number, head_sha, now):
    """The recovery lock serializes this write; the observer commits it."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT content FROM item_sections WHERE item_id={p} AND section_name={p}",
        (item_id, REENTRY_SECTION),
    ).fetchone()
    history = json.loads(row[0]) if row else {"receipts": []}
    history["receipts"].append({
        "pr_number": pr_number, "head_sha": head_sha,
        "accepted_at": format_instant(now), "automatic": True,
    })
    upsert_json_section(
        conn, item_id=item_id, section=REENTRY_SECTION, payload=history, ordering=211
    )
