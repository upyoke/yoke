"""Keep the model catalog on Yoke's shipped defaults unless an operator overrides it.

Each revision records its ``source``. While the latest revision is
``shipped``, every boot appends the build's shipped catalog when it differs,
so ``yoke update`` and each server release bring new model facts. An
``operator`` revision (``yoke models publish`` or ``restore``) is an override:
boot leaves it alone, reads report ``shipped_defaults_differ``, and
``yoke models follow-shipped`` returns the universe to the shipped defaults.
Revisions are append-only, so sessions keep the price basis they started on.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.model_reference_catalog import catalog_diff
from yoke_contracts.model_reference_records import ModelRecord
from yoke_contracts.timestamps import format_instant, parse_instant, utc_now
from yoke_core.domain.model_reference_store import (
    SOURCE_OPERATOR,
    SOURCE_SHIPPED,
    TABLE,
    insert_revision,
    latest_revision,
    lock_catalog,
    normalized_catalog,
    publish_catalog,
    revision_identity,
)

INITIAL_EFFECTIVE_AT = "1970-01-01T00:00:00.000000Z"
BOOT_NOTE = "Yoke's shipped model catalog, applied when this build started"
FOLLOW_NOTE = "Yoke's shipped model catalog, followed on operator request"


def shipped_catalog() -> tuple[tuple[ModelRecord, ...], str]:
    """This build's shipped records and their normalized stored document."""
    from yoke_contracts.model_reference_data import MODEL_RECORDS

    return normalized_catalog([record.to_dict() for record in MODEL_RECORDS])


def sync_shipped_catalog(conn: Any) -> Optional[str]:
    """Append this build's shipped catalog when the universe follows shipped defaults.

    An empty store gets the shipped catalog effective from the epoch. A store
    whose latest scheduled revision is shipped-sourced gets it effective now,
    unless the document equals any shipped revision already stored: then this
    build is the same or an older one rolled back, and appending would undo a
    newer build's catalog. An operator-sourced latest revision is never
    replaced. Returns the appended revision id, or ``None``.
    """
    _, document = shipped_catalog()
    lock_catalog(conn)
    rows = conn.execute(
        f"SELECT source,catalog_json,effective_at FROM {TABLE} "
        "ORDER BY effective_at DESC,published_at DESC,revision_id DESC"
    ).fetchall()
    now = utc_now()
    if not rows:
        when = parse_instant(INITIAL_EFFECTIVE_AT)
    elif rows[0][0] != SOURCE_SHIPPED or any(
        source == SOURCE_SHIPPED and stored == document for source, stored, _ in rows
    ):
        conn.commit()
        return None
    else:
        when = max(now, parse_instant(rows[0][2]))
    revision_id = revision_identity(when, SOURCE_SHIPPED, document)
    insert_revision(
        conn,
        revision_id=revision_id,
        effective_at=when,
        published_at=now,
        actor_id=None,
        document=document,
        source_note=BOOT_NOTE,
        source_revision_id=None,
        source=SOURCE_SHIPPED,
    )
    conn.commit()
    return revision_id


def shipped_defaults_differ(conn: Any) -> Optional[bool]:
    """Whether an operator override differs from this build's shipped catalog.

    ``None`` while the latest revision is shipped-sourced: the universe already
    follows shipped defaults.
    """
    latest = latest_revision(conn)
    if latest["source"] != SOURCE_OPERATOR:
        return None
    current = normalized_catalog([record.to_dict() for record in latest["records"]])
    return current[1] != shipped_catalog()[1]


def follow_shipped_catalog(conn: Any, *, actor_id: int) -> dict[str, Any]:
    """Make this build's shipped catalog current as a shipped-sourced revision.

    Already following an identical shipped catalog appends nothing. Otherwise
    the shipped catalog is published effective now, or at the latest scheduled
    revision's time when that is later, and later builds keep it current.
    """
    records, document = shipped_catalog()
    lock_catalog(conn)
    current = latest_revision(conn)
    current_document = normalized_catalog(
        [record.to_dict() for record in current["records"]]
    )[1]
    if current["source"] == SOURCE_SHIPPED and current_document == document:
        conn.commit()
        return {
            "appended": False,
            "revision_id": current["revision_id"],
            "effective_at": format_instant(current["effective_at"]),
            "published_at": format_instant(current["published_at"]),
            "count": len(records),
            "diff": catalog_diff(current["records"], records),
        }
    scheduled = current["effective_at"]
    result = publish_catalog(
        conn,
        [record.to_dict() for record in records],
        effective_at=scheduled if scheduled > utc_now() else None,
        actor_id=actor_id,
        source=SOURCE_SHIPPED,
        source_note=FOLLOW_NOTE,
        expected_base_revision_id=current["revision_id"],
    )
    return {"appended": True, **result}


__all__ = [
    "follow_shipped_catalog",
    "shipped_catalog",
    "shipped_defaults_differ",
    "sync_shipped_catalog",
]
