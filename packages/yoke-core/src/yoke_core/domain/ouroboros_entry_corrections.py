"""Supersede links between a corrected field note and its correction.

A correction filed as a fresh, unlinked note only sits next to the note
it corrects: both stay in the unreviewed queue and a reader has no way to
tell which one is current. Recording the link makes the relationship
durable in both directions and takes the corrected note out of the
unreviewed queue, so curate clusters the correction rather than the note
it replaced.

Storage is a link table rather than a column on ``ouroboros_entries``,
mirroring ``ouroboros_entry_dispositions``: the owning domain module
carries its own DDL, ``schema_init`` converges it at boot, and reads
guard on table presence so a partial fixture schema degrades to "no
links" instead of erroring.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


CORRECTIONS_TABLE = "ouroboros_entry_corrections"

_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {CORRECTIONS_TABLE} (
  correction_entry_id INTEGER PRIMARY KEY REFERENCES ouroboros_entries(id),
  corrected_entry_id INTEGER NOT NULL REFERENCES ouroboros_entries(id),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ouroboros_entry_corrections_corrected
  ON {CORRECTIONS_TABLE}(corrected_entry_id);
"""


class CorrectionTargetError(ValueError):
    """The note a correction claims to correct cannot be linked."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def ensure_ouroboros_entry_corrections_schema(conn: Any) -> None:
    """Create the additive correction link store."""
    execute_schema_script(conn, _SCHEMA_SQL)
    conn.commit()


def record_correction(
    conn: Any,
    *,
    correction_entry_id: int,
    corrected_entry_id: int,
) -> None:
    """Link a correction to the note it supersedes and retire that note.

    Raises :class:`CorrectionTargetError` when the corrected note does not
    exist or when a note is pointed at itself.
    """
    correction_id = int(correction_entry_id)
    corrected_id = int(corrected_entry_id)
    if correction_id == corrected_id:
        raise CorrectionTargetError(f"field note {corrected_id} cannot correct itself")

    ensure_ouroboros_entry_corrections_schema(conn)
    p = _p(conn)
    exists = conn.execute(
        f"SELECT 1 FROM ouroboros_entries WHERE id = {p}", (corrected_id,)
    ).fetchone()
    if exists is None:
        raise CorrectionTargetError(f"ouroboros entry {corrected_id} does not exist")

    now = iso8601_now()
    conn.execute(
        f"INSERT INTO {CORRECTIONS_TABLE} "
        "(correction_entry_id, corrected_entry_id, created_at) "
        f"VALUES ({p}, {p}, {p}) "
        "ON CONFLICT(correction_entry_id) DO NOTHING",
        (correction_id, corrected_id, now),
    )
    # Superseding is the point: the corrected note leaves the unreviewed
    # queue so it no longer competes with its own correction. An already
    # reviewed note keeps its original timestamp.
    conn.execute(
        "UPDATE ouroboros_entries "
        f"SET reviewed_at = COALESCE(reviewed_at, {p}) WHERE id = {p}",
        (now, corrected_id),
    )
    conn.commit()


def correction_links_by_entry_ids(
    conn: Any,
    entry_ids: Iterable[int],
) -> Dict[int, Dict[str, int]]:
    """Both directions of the supersede link, keyed by entry id.

    Each value carries ``corrects`` when the entry is a correction and
    ``superseded_by`` when the entry has been corrected.
    """
    ids = sorted({int(entry_id) for entry_id in entry_ids})
    if not ids or not _table_exists(conn, CORRECTIONS_TABLE):
        return {}

    p = _p(conn)
    markers = ", ".join(p for _ in ids)
    rows = conn.execute(
        "SELECT correction_entry_id, corrected_entry_id "
        f"FROM {CORRECTIONS_TABLE} "
        f"WHERE correction_entry_id IN ({markers}) "
        f"OR corrected_entry_id IN ({markers})",
        (*ids, *ids),
    ).fetchall()

    wanted = set(ids)
    links: Dict[int, Dict[str, int]] = {}
    for row in rows:
        correction_id = int(row_value(row, "correction_entry_id", 0))
        corrected_id = int(row_value(row, "corrected_entry_id", 1))
        if correction_id in wanted:
            links.setdefault(correction_id, {})["corrects"] = corrected_id
        if corrected_id in wanted:
            links.setdefault(corrected_id, {})["superseded_by"] = correction_id
    return links


__all__ = [
    "CORRECTIONS_TABLE",
    "CorrectionTargetError",
    "correction_links_by_entry_ids",
    "ensure_ouroboros_entry_corrections_schema",
    "record_correction",
]
