"""Seeding helpers for the session-holdings read: sessions and the
claims they hold.

Shared by the holdings-projection tests and the per-claim-facts tests,
which seed the same rows and would otherwise each carry their own copy.
Public names are shared by roster, claim lifecycle and QA suites.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.db_helpers import instant_parameter

from yoke_core.domain.work_claim_targets import (
    make_item_target,
    make_migration_serialization_target,
    make_qa_admission_target,
    make_steering_target,
)


def instant_ago(minutes_ago: int = 0) -> datetime:
    return parse_instant(utc_now()) - timedelta(minutes=minutes_ago)


def _optional_parameter(conn, value: str | datetime | None):
    return None if value is None else instant_parameter(conn, parse_instant(value))


def insert_session(
    conn,
    session_id: str,
    *,
    current_item_id: str | None = None,
    ended_at: str | datetime | None = None,
) -> None:
    """Seed one harness session, optionally already ended.

    ``ended_at`` seeds a session that is gone: readers that ask who is
    actually holding an item need one to prove a leftover claim does not
    count as a holder.
    """
    ended = _optional_parameter(conn, ended_at)
    now = instant_parameter(conn, instant_ago())
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_level, workspace, "
        "project_id, mode, offered_at, last_heartbeat, current_item_id, "
        "ended_at"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            "claude-code",
            "anthropic",
            "test-model",
            "primary",
            "/tmp/workspace",
            1,
            "wait",
            now,
            now,
            current_item_id,
            ended,
        ),
    )
    conn.commit()


def insert_item_claim(
    conn,
    session_id: str,
    item_id: int,
    *,
    released_at: str | datetime | None = None,
) -> None:
    released = _optional_parameter(conn, released_at)
    now = instant_parameter(conn, instant_ago())
    conn.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, scope, claimed_at, last_heartbeat, reason, "
        "released_at, release_reason"
        ") VALUES (%s, 'item', %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            make_item_target(item_id).scope_json(),
            now,
            now,
            "implementation",
            released,
            "completed" if released is not None else None,
        ),
    )
    conn.commit()


def insert_steering_claim(
    conn,
    session_id: str,
    *,
    project_id: int = 1,
    document: str | None = None,
    released_at: str | datetime | None = None,
) -> int:
    released = _optional_parameter(conn, released_at)
    now = instant_parameter(conn, instant_ago())
    row = conn.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, scope, claimed_at, last_heartbeat, reason, "
        "released_at, release_reason"
        ") VALUES (%s, 'steering', %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            session_id,
            make_steering_target(project_id, document=document).scope_json(),
            now,
            now,
            "strategy review",
            released,
            "released" if released is not None else None,
        ),
    ).fetchone()
    conn.commit()
    return int(row[0])


def insert_document_lock(
    conn,
    session_id: str,
    project_id: int,
    slug: str,
    *,
    steering_claim_id: int | None = None,
) -> None:
    """Lock one strategy document to a session, seeding the document itself.

    ``strategy_doc_claims`` carries a foreign key onto ``strategy_docs``,
    so a lock cannot exist without the document it locks.
    """
    now = instant_parameter(conn, instant_ago())
    conn.execute(
        "INSERT INTO strategy_docs (project_id, slug, updated_at) "
        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (project_id, slug, now),
    )
    conn.execute(
        "INSERT INTO strategy_doc_claims ("
        "project_id, strategy_doc_slug, owner_kind, owner_session_id, "
        "registered_at, steering_claim_id"
        ") VALUES (%s, %s, 'session', %s, %s, %s)",
        (project_id, slug, session_id, now, steering_claim_id),
    )
    conn.commit()


def insert_lease(
    conn,
    *,
    session_id: str,
    lease_key: str,
    owner_kind: str = "session",
    owner_session_id: str | None = None,
    owner_item_id: int | None = None,
    released_at: str | datetime | None = None,
) -> None:
    """Seed one shared-operation coordination claim by its operator key.

    The key decides the kind: migration territory is always item-owned,
    a physical host is always session-held.
    """
    released = _optional_parameter(conn, released_at)
    now = instant_parameter(conn, instant_ago())
    del owner_kind, owner_session_id
    prefix, resource = lease_key.split(":", 1)
    if prefix == "LIVE_DB_MIGRATION":
        target = make_migration_serialization_target(1, resource, int(owner_item_id))
    else:
        target = make_qa_admission_target(resource)
    conn.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, scope, claimed_at, last_heartbeat, "
        "released_at, release_reason"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            target.kind,
            target.scope_json(),
            now,
            now,
            released,
            "completed" if released is not None else None,
        ),
    )
    conn.commit()


def insert_session_path_claim(
    conn, session_id: str, *, released_at: str | datetime | None = None
) -> None:
    released = _optional_parameter(conn, released_at)
    now = instant_parameter(conn, instant_ago())
    actor_id = int(
        conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    conn.execute(
        "INSERT INTO path_claims (state,mode,owner_kind,owner_session_id,"
        "registered_by_actor_id,integration_target,registered_at,released_at) "
        "VALUES (%s,'exclusive','session',%s,%s,'main',%s,%s)",
        (
            "released" if released is not None else "active",
            session_id,
            actor_id,
            now,
            released,
        ),
    )
    conn.commit()


__all__ = [
    "insert_document_lock",
    "insert_item_claim",
    "insert_lease",
    "insert_session",
    "insert_session_path_claim",
    "insert_steering_claim",
    "instant_ago",
]
