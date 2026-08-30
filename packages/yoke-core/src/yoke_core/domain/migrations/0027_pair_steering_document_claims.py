"""Backfill the durable strategy-document link for active steering seats."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "strategy_doc_claims"
PAIR_COLUMN = "paired_work_claim_id"
# Frozen migration snapshot; live code owns the shared default constant.
DEFAULT_DOC_SLUG = "CURRENT-PLAN"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def apply(conn: Any) -> None:
    if not _table_exists(conn, TABLE) or not _table_exists(conn, "work_claims"):
        return
    _add_column_if_not_exists(conn, TABLE, PAIR_COLUMN, "INTEGER DEFAULT NULL")
    for seat in conn.execute(
        "SELECT id, session_id, scope, claimed_at FROM work_claims "
        "WHERE target_kind = 'steering' AND released_at IS NULL "
        "ORDER BY id"
    ).fetchall():
        _pair_active_seat(conn, seat)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_strategy_doc_claims_paired_work_claim "
        f"ON {TABLE}({PAIR_COLUMN}) WHERE {PAIR_COLUMN} IS NOT NULL"
    )


def _pair_active_seat(conn: Any, seat: Any) -> None:
    seat = dict(seat)
    claim_id = int(seat["id"])
    project_id = int(json.loads(str(seat["scope"]))["project_id"])
    p = _p(conn)
    paired = conn.execute(
        f"SELECT id FROM {TABLE} WHERE {PAIR_COLUMN} = {p} AND released_at IS NULL",
        (claim_id,),
    ).fetchall()
    if len(paired) == 1:
        return
    if paired:
        raise AssertionError(
            f"steering claim {claim_id} has multiple active document pairs"
        )

    held = conn.execute(
        f"SELECT id, strategy_doc_slug FROM {TABLE} "
        "WHERE owner_kind = 'session' AND owner_session_id = "
        f"{p} AND project_id = {p} AND released_at IS NULL ORDER BY id",
        (str(seat["session_id"]), project_id),
    ).fetchall()
    current = [row for row in held if str(row["strategy_doc_slug"]) == DEFAULT_DOC_SLUG]
    if current:
        chosen = current[0]
    elif len(held) == 1:
        chosen = held[0]
    elif held:
        raise AssertionError(
            f"steering claim {claim_id} has multiple unpaired document locks; "
            "release all but the intended steering document and retry migration"
        )
    else:
        chosen = _insert_default_pair(conn, seat, project_id)
    conn.execute(
        f"UPDATE {TABLE} SET {PAIR_COLUMN} = {p} WHERE id = {p}",
        (claim_id, int(chosen["id"])),
    )


def _insert_default_pair(conn: Any, seat: dict[str, Any], project_id: int) -> Any:
    p = _p(conn)
    doc = conn.execute(
        f"SELECT slug FROM strategy_docs WHERE project_id = {p} AND slug = {p}",
        (project_id, DEFAULT_DOC_SLUG),
    ).fetchone()
    if doc is None:
        raise AssertionError(
            f"project {project_id} has an active steering seat but no "
            f"{DEFAULT_DOC_SLUG}; seed the default strategy corpus and retry"
        )
    conflict = conn.execute(
        f"SELECT id FROM {TABLE} WHERE project_id = {p} "
        f"AND strategy_doc_slug = {p} AND released_at IS NULL",
        (project_id, DEFAULT_DOC_SLUG),
    ).fetchone()
    if conflict is not None:
        raise AssertionError(
            f"project {project_id} {DEFAULT_DOC_SLUG} is held elsewhere; "
            "release that document lock and retry migration"
        )
    actor = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id = {p}",
        (str(seat["session_id"]),),
    ).fetchone()
    actor_id = None if actor is None else actor["actor_id"]
    return conn.execute(
        f"INSERT INTO {TABLE} "
        "(project_id, strategy_doc_slug, owner_kind, owner_session_id, "
        "registered_by_actor_id, registered_by_session_id, registered_at) "
        f"VALUES ({p}, {p}, 'session', {p}, {p}, {p}, {p}) RETURNING id",
        (
            project_id,
            DEFAULT_DOC_SLUG,
            str(seat["session_id"]),
            actor_id,
            str(seat["session_id"]),
            str(seat["claimed_at"]),
        ),
    ).fetchone()


def invariants(conn: Any) -> None:
    if not _table_exists(conn, TABLE) or not _table_exists(conn, "work_claims"):
        return
    assert _column_exists(conn, TABLE, PAIR_COLUMN)
    for seat in conn.execute(
        "SELECT id, session_id, scope FROM work_claims "
        "WHERE target_kind = 'steering' AND released_at IS NULL"
    ).fetchall():
        seat = dict(seat)
        project_id = int(json.loads(str(seat["scope"]))["project_id"])
        rows = conn.execute(
            f"SELECT project_id, owner_session_id FROM {TABLE} "
            f"WHERE {PAIR_COLUMN} = {_p(conn)} AND released_at IS NULL",
            (int(seat["id"]),),
        ).fetchall()
        assert len(rows) == 1, f"steering claim {seat['id']} lacks one active pair"
        assert int(rows[0]["project_id"]) == project_id
        assert str(rows[0]["owner_session_id"]) == str(seat["session_id"])


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
