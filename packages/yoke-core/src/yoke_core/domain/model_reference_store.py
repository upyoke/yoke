"""Authoritative, effective-dated model catalog revisions."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from yoke_contracts.model_reference_catalog import catalog_diff, validate_catalog
from yoke_contracts.model_reference_records import ModelRecord, ModelReferenceError
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.schema_init_apply import execute_schema_script

TABLE = "model_reference_revisions"
INITIAL_EFFECTIVE_AT = "1970-01-01T00:00:00.000000Z"


def create_model_reference_table(conn: Any) -> None:
    """Add the catalog store without changing any existing table."""
    execute_schema_script(
        conn,
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
          revision_id TEXT PRIMARY KEY,
          effective_at TEXT NOT NULL,
          published_at TEXT NOT NULL,
          published_by_actor_id INTEGER,
          catalog_json TEXT NOT NULL,
          source_note TEXT NOT NULL,
          source_revision_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_model_reference_effective
          ON {TABLE}(effective_at DESC, published_at DESC, revision_id DESC);
        """,
    )


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelReferenceError(
            "effective_at_invalid", "effective_at must be an ISO-8601 UTC datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ModelReferenceError(
            "effective_at_invalid", "effective_at must have a UTC offset"
        )
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _normalized_catalog(raw: object) -> tuple[tuple[ModelRecord, ...], str]:
    records = validate_catalog(raw)
    document = json_helper.dumps_pretty([record.to_dict() for record in records])
    return records, document


def _revision(row: Any) -> dict[str, Any]:
    return {
        "revision_id": row[0],
        "effective_at": row[1],
        "published_at": row[2],
        "published_by_actor_id": row[3],
        "records": validate_catalog(json_helper.loads_text(row[4])),
        "source_note": row[5],
        "source_revision_id": row[6],
    }


def _select(conn: Any, *, effective_at: str | None = None) -> dict[str, Any] | None:
    marker = _marker(conn)
    clause = f"WHERE effective_at <= {marker}" if effective_at else ""
    params = (effective_at,) if effective_at else ()
    row = conn.execute(
        "SELECT revision_id,effective_at,published_at,published_by_actor_id,"
        "catalog_json,source_note,source_revision_id "
        f"FROM {TABLE} {clause} "
        "ORDER BY effective_at DESC,published_at DESC,revision_id DESC LIMIT 1",
        params,
    ).fetchone()
    return _revision(row) if row else None


def revision_at(conn: Any, at: str | None = None) -> dict[str, Any]:
    """Read the published revision effective at a session's initial start."""
    when = _stamp(_utc(at)) if at else _stamp(datetime.now(timezone.utc))
    revision = _select(conn, effective_at=when)
    if revision is None:
        raise ModelReferenceError(
            "revision_missing",
            "No model catalog covers this time; publish a catalog revision",
        )
    return revision


def latest_revision(conn: Any) -> dict[str, Any]:
    """Read the last scheduled revision, including one not yet effective."""
    revision = _select(conn)
    if revision is None:
        raise ModelReferenceError("revision_missing", "No model catalog is published")
    return revision


def revisions_list(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT revision_id,effective_at,published_at,published_by_actor_id,"
        "source_note,source_revision_id "
        f"FROM {TABLE} ORDER BY effective_at DESC,published_at DESC,revision_id DESC"
    ).fetchall()
    return [
        {
            "revision_id": row[0],
            "effective_at": row[1],
            "published_at": row[2],
            "published_by_actor_id": row[3],
            "source_note": row[4],
            "source_revision_id": row[5],
        }
        for row in rows
    ]


def revision_get(conn: Any, revision_id: str) -> dict[str, Any]:
    marker = _marker(conn)
    row = conn.execute(
        "SELECT revision_id,effective_at,published_at,published_by_actor_id,"
        "catalog_json,source_note,source_revision_id "
        f"FROM {TABLE} WHERE revision_id={marker}",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise ModelReferenceError(
            "revision_unknown", f"{revision_id} is unknown; list model revisions"
        )
    return _revision(row)


def preview_catalog(conn: Any, raw: object) -> dict[str, Any]:
    candidate, _ = _normalized_catalog(raw)
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
    effective_at: str | None,
    actor_id: int,
    source_note: str,
    expected_base_revision_id: str,
    source_revision_id: str | None = None,
) -> dict[str, Any]:
    """Atomically publish one whole candidate, refusing stale or past edits."""
    if not source_note.strip():
        raise ModelReferenceError(
            "source_note_missing", "publication needs a source note and evidence"
        )
    now = datetime.now(timezone.utc)
    when = _utc(effective_at) if effective_at else now
    if when < now:
        raise ModelReferenceError(
            "effective_at_past",
            "effective_at predates publication; choose now or a future UTC time",
        )
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('model_reference_revisions'))"
        )
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
    records, document = _normalized_catalog(raw)
    effective = _stamp(when)
    revision_id = sha256((effective + "\n" + document).encode()).hexdigest()
    marker = _marker(conn)
    existing = conn.execute(
        f"SELECT published_at FROM {TABLE} WHERE revision_id={marker}",
        (revision_id,),
    ).fetchone()
    if existing is None:
        placeholders = ",".join([marker] * 7)
        conn.execute(
            f"INSERT INTO {TABLE} (revision_id,effective_at,published_at,"
            "published_by_actor_id,catalog_json,source_note,source_revision_id) "
            f"VALUES ({placeholders})",
            (
                revision_id,
                effective,
                _stamp(now),
                actor_id,
                document,
                source_note.strip(),
                source_revision_id,
            ),
        )
    conn.commit()
    return {
        "revision_id": revision_id,
        "effective_at": effective,
        "published_at": existing[0] if existing else _stamp(now),
        "count": len(records),
        "diff": catalog_diff(current["records"], records),
    }


def seed_initial_catalog(conn: Any) -> None:
    """Bootstrap only an empty store; operator publications remain untouched."""
    if conn.execute(f"SELECT 1 FROM {TABLE} LIMIT 1").fetchone():
        return
    from yoke_contracts.model_reference_data import MODEL_RECORDS

    records, document = _normalized_catalog(
        [record.to_dict() for record in MODEL_RECORDS]
    )
    revision_id = sha256((INITIAL_EFFECTIVE_AT + "\n" + document).encode()).hexdigest()
    marker = _marker(conn)
    placeholders = ",".join([marker] * 7)
    conn.execute(
        f"INSERT INTO {TABLE} (revision_id,effective_at,published_at,"
        "published_by_actor_id,catalog_json,source_note,source_revision_id) "
        f"VALUES ({placeholders}) ON CONFLICT (revision_id) DO NOTHING",
        (
            revision_id,
            INITIAL_EFFECTIVE_AT,
            _stamp(datetime.now(timezone.utc)),
            None,
            document,
            "Initial researched catalog bundled with this build",
            None,
        ),
    )
    conn.commit()
    assert records


__all__ = [
    "create_model_reference_table",
    "preview_catalog",
    "publish_catalog",
    "latest_revision",
    "revision_at",
    "revision_get",
    "revisions_list",
    "seed_initial_catalog",
]
