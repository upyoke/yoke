"""Retire item-level Browser QA configuration after method-plan parity."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    load_item_workflow_runtime,
)

MIGRATION_NAME = "workflow_item_browser_qa_metadata_contract"
_RETIRED_COLUMN = "browser_qa_metadata"
_BROWSER_METHOD_IDS = ("browser-check", "browser-inspection")
_BROWSER_QA_KINDS = ("browser_smoke", "browser_diff")


def _browser_configured(raw: Any) -> bool:
    if raw is None:
        return False
    payload = raw if isinstance(raw, dict) else json.loads(str(raw))
    return bool(payload.get("browser_testable"))


def _require_materialized_browser_qa(conn: Any) -> None:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    has_method_id = _column_exists(conn, "qa_requirements", "method_id")
    requirement_clause = (
        "method_id IN (%s, %s) OR qa_kind IN (%s, %s)"
        if has_method_id
        else "qa_kind IN (%s, %s)"
    )
    requirement_args: tuple[str, ...] = (
        *_BROWSER_METHOD_IDS,
        *_BROWSER_QA_KINDS,
    ) if has_method_id else _BROWSER_QA_KINDS

    missing: list[int] = []
    rows = conn.execute(
        "SELECT id, status, browser_qa_metadata "
        "FROM items ORDER BY id"
    ).fetchall()
    for item_id, status, metadata in rows:
        if not _browser_configured(metadata):
            continue
        runtime = load_item_workflow_runtime(conn, int(item_id))
        stage_id = str(status)
        if (
            stage_id in runtime.terminal_stage_ids
            or stage_id in ENGINE_TERMINAL_STAGE_IDS
        ):
            continue
        row = conn.execute(
            "SELECT 1 FROM qa_requirements "
            f"WHERE item_id={marker} AND ({requirement_clause}) LIMIT 1",
            (int(item_id), *requirement_args),
        ).fetchone()
        if row is None:
            missing.append(int(item_id))
    if missing:
        sample = ", ".join(str(item_id) for item_id in missing[:5])
        raise AssertionError(
            "browser-configured active items lack materialized Browser QA: "
            + sample
        )


def apply(conn: Any) -> None:
    """Drop item Browser QA metadata only after executable parity exists."""
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError(
            "workflow item Browser QA metadata contraction requires PostgreSQL"
        )
    if not _table_exists(conn, "items"):
        raise AssertionError("items table is required before this migration")
    if not _column_exists(conn, "items", _RETIRED_COLUMN):
        return
    if not _table_exists(conn, "qa_requirements"):
        raise AssertionError("qa_requirements must exist before contraction")

    conn.execute("LOCK TABLE items IN ACCESS EXCLUSIVE MODE")
    before = int(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
    _require_materialized_browser_qa(conn)
    conn.execute(f"ALTER TABLE items DROP COLUMN {_RETIRED_COLUMN}")
    after = int(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
    if after != before:
        raise AssertionError(f"items row count changed from {before} to {after}")


def invariants(conn: Any) -> None:
    """Verify item storage no longer carries Browser QA configuration."""
    if not _table_exists(conn, "items"):
        raise AssertionError("items table is missing")
    if _column_exists(conn, "items", _RETIRED_COLUMN):
        raise AssertionError("retired Browser QA metadata column is still present")


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
