"""Authoritative, effective-dated model catalog revisions."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any

from yoke_contracts.model_reference_catalog import (
    catalog_diff,
    refuse_retired_record_keys,
    validate_catalog,
)
from yoke_contracts.model_reference_records import ModelRecord, ModelReferenceError
from yoke_contracts.timestamps import (
    InvalidInstant,
    format_instant,
    parse_instant,
    temporal_wire,
    utc_now,
)
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.schema_init_apply import execute_schema_script

TABLE = "model_reference_revisions"
SOURCE_SHIPPED = "shipped"
SOURCE_OPERATOR = "operator"
SOURCES = (SOURCE_SHIPPED, SOURCE_OPERATOR)
_COLUMNS = (
    "revision_id,effective_at,published_at,published_by_actor_id,"
    "catalog_json,source_note,source_revision_id,source"
)


def create_model_reference_table(conn: Any) -> None:
    """Add the catalog store without changing any existing table."""
    execute_schema_script(
        conn,
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
          revision_id TEXT PRIMARY KEY,
          effective_at TIMESTAMPTZ NOT NULL,
          published_at TIMESTAMPTZ NOT NULL,
          published_by_actor_id INTEGER,
          catalog_json TEXT NOT NULL,
          source_note TEXT NOT NULL,
          source_revision_id TEXT,
          source TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_model_reference_effective
          ON {TABLE}(effective_at DESC, published_at DESC, revision_id DESC);
        """,
    )


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _utc(value: datetime | str) -> datetime:
    try:
        return parse_instant(value)
    except InvalidInstant as exc:
        raise ModelReferenceError("invalid_instant", str(exc)) from exc


def _stamp(value: datetime) -> str:
    return format_instant(value)


def normalized_catalog(raw: object) -> tuple[tuple[ModelRecord, ...], str]:
    """Validate a candidate catalog; stored history is read as written."""
    for entry in raw if isinstance(raw, list) else ():
        if isinstance(entry, dict):
            refuse_retired_record_keys(entry)
    records = validate_catalog(raw)
    document = json_helper.dumps_pretty([record.to_dict() for record in records])
    return records, document


def _revision(row: Any) -> dict[str, Any]:
    return {
        "revision_id": row[0],
        "effective_at": _utc(row[1]),
        "published_at": _utc(row[2]),
        "published_by_actor_id": row[3],
        "records": validate_catalog(json_helper.loads_text(row[4])),
        "source_note": row[5],
        "source_revision_id": row[6],
        "source": row[7],
    }


def _select(
    conn: Any, *, effective_at: datetime | None = None
) -> dict[str, Any] | None:
    marker = _marker(conn)
    clause = f"WHERE effective_at <= {marker}" if effective_at is not None else ""
    params = (
        (instant_parameter(conn, effective_at),) if effective_at is not None else ()
    )
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM {TABLE} {clause} "
        "ORDER BY effective_at DESC,published_at DESC,revision_id DESC LIMIT 1",
        params,
    ).fetchone()
    return _revision(row) if row else None


def revision_at(conn: Any, at: datetime | str | None = None) -> dict[str, Any]:
    """Read the published revision effective at a session's initial start."""
    when = _utc(at) if at is not None else utc_now()
    revision = _select(conn, effective_at=when)
    if revision is None:
        raise ModelReferenceError(
            "revision_missing",
            "No model catalog covers this time; publish a catalog revision",
        )
    return revision


def revision_schedule(conn: Any) -> list[dict[str, Any]]:
    """Load each catalog once for readers projecting a page of sessions."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM {TABLE} ORDER BY effective_at DESC,published_at DESC,revision_id DESC"
    ).fetchall()
    return [_revision(row) for row in rows]


def revision_from_schedule(
    schedule: list[dict[str, Any]], at: datetime | str | None
) -> dict[str, Any]:
    """Select a session's revision without another database statement."""
    when = _utc(at) if at is not None else utc_now()
    for revision in schedule:
        if _utc(revision["effective_at"]) <= when:
            return revision
    raise ModelReferenceError(
        "revision_missing",
        "No model catalog covers this time; publish a catalog revision",
    )


def latest_revision(conn: Any) -> dict[str, Any]:
    """Read the last scheduled revision, including one not yet effective."""
    revision = _select(conn)
    if revision is None:
        raise ModelReferenceError("revision_missing", "No model catalog is published")
    return revision


def revisions_list(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT revision_id,effective_at,published_at,published_by_actor_id,"
        "source_note,source_revision_id,source "
        f"FROM {TABLE} ORDER BY effective_at DESC,published_at DESC,revision_id DESC"
    ).fetchall()
    return temporal_wire(
        [
            {
                "revision_id": row[0],
                "effective_at": _utc(row[1]),
                "published_at": _utc(row[2]),
                "published_by_actor_id": row[3],
                "source_note": row[4],
                "source_revision_id": row[5],
                "source": row[6],
            }
            for row in rows
        ]
    )


def revision_get(conn: Any, revision_id: str) -> dict[str, Any]:
    marker = _marker(conn)
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM {TABLE} WHERE revision_id={marker}",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise ModelReferenceError(
            "revision_unknown", f"{revision_id} is unknown; list model revisions"
        )
    return _revision(row)


def preview_catalog(conn: Any, raw: object) -> dict[str, Any]:
    candidate, _ = normalized_catalog(raw)
    current = latest_revision(conn)
    return {
        "base_revision_id": current["revision_id"],
        "count": len(candidate),
        "diff": catalog_diff(current["records"], candidate),
    }


def publish_catalog(
    conn: Any,
    raw: object,
    *,
    effective_at: datetime | str | None,
    actor_id: int,
    source: str,
    source_note: str,
    expected_base_revision_id: str,
    source_revision_id: str | None = None,
) -> dict[str, Any]:
    """Atomically publish one whole candidate, refusing stale or past edits.

    ``source`` says whose catalog this is: ``operator`` (an override boot never
    replaces) or ``shipped`` (Yoke's defaults, which later builds keep current).
    """
    if source not in SOURCES:
        raise ModelReferenceError(
            "source_invalid", f"source must be one of {', '.join(SOURCES)}"
        )
    if not source_note.strip():
        raise ModelReferenceError(
            "source_note_missing", "publication needs a source note and evidence"
        )
    now = utc_now()
    when = _utc(effective_at) if effective_at is not None else now
    if when < now:
        raise ModelReferenceError(
            "effective_at_past",
            "effective_at predates publication; choose now or a future UTC time",
        )
    lock_catalog(conn)
    current = latest_revision(conn)
    if current["revision_id"] != expected_base_revision_id:
        raise ModelReferenceError(
            "catalog_stale",
            "latest catalog changed; inspect a fresh models diff before publishing",
        )
    if when < _utc(current["effective_at"]):
        raise ModelReferenceError(
            "effective_at_order",
            "effective_at precedes the latest scheduled revision; choose that time or later",
        )
    records, document = normalized_catalog(raw)
    effective = _stamp(when)
    revision_id = revision_identity(when, source, document)
    marker = _marker(conn)
    existing = conn.execute(
        f"SELECT published_at FROM {TABLE} WHERE revision_id={marker}",
        (revision_id,),
    ).fetchone()
    if existing is None:
        insert_revision(
            conn,
            revision_id=revision_id,
            effective_at=when,
            published_at=now,
            actor_id=actor_id,
            document=document,
            source_note=source_note.strip(),
            source_revision_id=source_revision_id,
            source=source,
        )
    conn.commit()
    return {
        "revision_id": revision_id,
        "effective_at": effective,
        "published_at": format_instant(existing[0]) if existing else _stamp(now),
        "count": len(records),
        "diff": catalog_diff(current["records"], records),
    }


def revision_identity(effective_at: datetime, source: str, document: str) -> str:
    """Content address of one scheduled catalog document and whose it is."""
    key = "\n".join((_stamp(effective_at), source, document))
    return sha256(key.encode()).hexdigest()


def lock_catalog(conn: Any) -> None:
    """Serialize catalog writers for the rest of this transaction."""
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('model_reference_revisions'))"
        )


def insert_revision(
    conn: Any,
    *,
    revision_id: str,
    effective_at: datetime,
    published_at: datetime,
    actor_id: int | None,
    document: str,
    source_note: str,
    source_revision_id: str | None,
    source: str,
) -> None:
    marker = _marker(conn)
    placeholders = ",".join([marker] * 8)
    conn.execute(
        f"INSERT INTO {TABLE} ({_COLUMNS}) VALUES ({placeholders})",
        (
            revision_id,
            instant_parameter(conn, effective_at),
            instant_parameter(conn, published_at),
            actor_id,
            document,
            source_note,
            source_revision_id,
            source,
        ),
    )


__all__ = [
    "SOURCE_OPERATOR",
    "SOURCE_SHIPPED",
    "create_model_reference_table",
    "insert_revision",
    "lock_catalog",
    "preview_catalog",
    "publish_catalog",
    "latest_revision",
    "normalized_catalog",
    "revision_at",
    "revision_from_schedule",
    "revision_get",
    "revision_identity",
    "revision_schedule",
    "revisions_list",
]
