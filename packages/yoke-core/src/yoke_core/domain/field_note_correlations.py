"""Bounded durable repeat projections shared by CLI and browser readers."""

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.ouroboros_entry_presentation import entry_wire_value

REPEAT_PAGE_LIMIT = 20


def attach_correlations(conn, entries):
    """Attach root id, repeat count and bounded evidence to each returned note."""
    if not entries:
        return
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    ids = [entry["id"] for entry in entries]
    marks = ",".join([p] * len(ids))
    roots = dict(
        query_rows(
            conn,
            f"SELECT id, correlation_id FROM ouroboros_entries WHERE id IN ({marks})",
            tuple(ids),
        )
    )
    rows = query_rows(
        conn,
        "SELECT id, correlation_id, timestamp, agent, body, total FROM ("
        "SELECT id, correlation_id, timestamp, agent, body, "
        "COUNT(*) OVER (PARTITION BY correlation_id) AS total, "
        "ROW_NUMBER() OVER (PARTITION BY correlation_id ORDER BY id DESC) AS position "
        f"FROM ouroboros_entries WHERE correlation_id IN ({marks})) repeats "
        f"WHERE position<={p} ORDER BY id DESC",
        (*ids, REPEAT_PAGE_LIMIT),
    )
    by_root = {}
    for row in rows:
        by_root.setdefault(row[1], []).append(
            {
                "id": int(row[0]),
                "timestamp": entry_wire_value("timestamp", row[2]),
                "agent": row[3],
                "preview": " ".join(row[4].split())[:120],
            }
        )
    counts = {row[1]: int(row[5]) for row in rows}
    for entry in entries:
        entry["correlation_id"] = roots.get(entry["id"])
        entry["repeat_count"] = counts.get(entry["id"], 0)
        entry["repeats"] = by_root.get(entry["id"], [])
