"""How a durable table's rows pair with the events they should produce.

The declared pairs below are what ``HC-event-family-liveness`` reads. Each
names a table whose recent rows imply telemetry, the event that telemetry is,
and the column carrying the activity timestamp.

A pair may also name the column that distinguishes the table's write paths.
That matters because a family-wide count only answers "did anything emit?",
and one healthy path answers that for every silent path sharing the table —
which is exactly how a creation path that emitted nothing stayed green behind
a sibling that did. When a pair declares its write-path column, pairing joins
each row to its own event through the row id in the event envelope and groups
by that column, so a silent path is named while its siblings stay healthy.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.domain.db_helpers import query_rows


__all__ = (
    "EVENT_FAMILY_JOIN_WINDOW_DAYS",
    "EVENT_FAMILY_LIVENESS_PAIRS",
    "EventFamilyLivenessPair",
    "unpaired_write_paths",
)


EVENT_FAMILY_JOIN_WINDOW_DAYS = 7


@dataclass(frozen=True)
class EventFamilyLivenessPair:
    """One durable activity source and the telemetry it should produce."""

    durable_table: str
    expected_event: str
    activity_column: str
    join_window_days: int
    #: Column whose distinct values name the write paths feeding this table.
    #: Set it when the table has several creation paths. Requires
    #: ``event_row_id_key``.
    write_path_column: str | None = None
    #: Key under ``$.context.detail`` in the event envelope carrying the
    #: durable row's ``id``, which is what makes per-row pairing possible.
    event_row_id_key: str | None = None


EVENT_FAMILY_LIVENESS_PAIRS = (
    EventFamilyLivenessPair(
        "items", "ItemStatusChanged", "updated_at", EVENT_FAMILY_JOIN_WINDOW_DAYS
    ),
    EventFamilyLivenessPair(
        "qa_requirements",
        "QARequirementCreated",
        "created_at",
        EVENT_FAMILY_JOIN_WINDOW_DAYS,
        write_path_column="requirement_source",
        event_row_id_key="requirement_id",
    ),
    EventFamilyLivenessPair(
        "qa_runs", "QARunCompleted", "completed_at", EVENT_FAMILY_JOIN_WINDOW_DAYS
    ),
    EventFamilyLivenessPair(
        "harness_sessions", "HarnessSessionStarted", "offered_at",
        EVENT_FAMILY_JOIN_WINDOW_DAYS,
    ),
)


def unpaired_write_paths(
    conn, pair: EventFamilyLivenessPair, cutoff: str
) -> list[str]:
    """Describe each write path whose recent rows outnumber their events."""
    rows = query_rows(
        conn,
        f"SELECT r.{pair.write_path_column} AS write_path, "
        "COUNT(*) AS durable_rows, COUNT(paired.row_id) AS paired_rows "
        f"FROM {pair.durable_table} r LEFT JOIN ("
        "SELECT DISTINCT "
        "(envelope::jsonb -> 'context' -> 'detail' ->> %s)::bigint AS row_id "
        f"FROM events WHERE event_name = %s AND created_at >= {cutoff}"
        ") paired ON paired.row_id = r.id "
        f"WHERE r.{pair.activity_column} IS NOT NULL "
        f"AND r.{pair.activity_column} >= {cutoff} "
        "GROUP BY 1 ORDER BY 1",
        (pair.event_row_id_key, pair.expected_event),
    )
    dark: list[str] = []
    for row in rows:
        durable = int(row["durable_rows"] or 0)
        paired = int(row["paired_rows"] or 0)
        if paired >= durable:
            continue
        dark.append(
            f"- {pair.durable_table}[{pair.write_path_column}="
            f"{row['write_path']}]: {durable} recent row(s), {paired} paired "
            f"{pair.expected_event} event(s), {durable - paired} unpaired"
        )
    return dark
