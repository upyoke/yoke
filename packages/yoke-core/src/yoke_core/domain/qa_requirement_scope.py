"""Serialize QA attempt and correction writes within their obligation scope."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.schema_common import _table_exists


def lock_requirement_scope(conn: Any, requirement_id: int) -> None:
    """Keep selection, judgment and graph validation atomic with new attempts.

    Existing row locks protect a pair, but disjoint pairs can concurrently
    close a longer correction cycle. An advisory transaction lock serializes
    the same obligation scope without adding persisted state or a new claim.
    """
    if not db_backend.connection_is_postgres(conn) or not _table_exists(
        conn, "qa_requirements"
    ):
        return
    from yoke_core.domain.qa_requirement_supersession import requirement_scope

    row = query_one(
        conn, "SELECT * FROM qa_requirements WHERE id=%s", (int(requirement_id),)
    )
    if row is None:
        return
    scope = json.dumps(requirement_scope(dict(row)), separators=(",", ":"))
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        ("qa-requirement-scope:" + scope,),
    )
