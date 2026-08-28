"""Seeding helpers for the session-holdings read: sessions and the
claims they hold.

Shared by the holdings-projection tests and the per-claim-facts tests,
which seed the same rows and would otherwise each carry their own copy.
Public names because two modules read them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.domain.work_claim_targets import (
    make_item_target,
    make_migration_serialization_target,
    make_qa_admission_target,
    make_steering_target,
)


def iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_session(
    conn, session_id: str, *, current_item_id: str | None = None
) -> None:
    now = iso()
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, current_item_id"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
        ),
    )
    conn.commit()


def insert_item_claim(
    conn,
    session_id: str,
    item_id: int,
    *,
    released_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, scope, claimed_at, last_heartbeat, reason, "
        "released_at, release_reason"
        ") VALUES (%s, 'item', %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            make_item_target(item_id).scope_json(),
            iso(),
            iso(),
            "implementation",
            released_at,
            "completed" if released_at else None,
        ),
    )
    conn.commit()


def insert_steering_claim(conn, session_id: str) -> None:
    now = iso()
    conn.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, scope, claimed_at, last_heartbeat, reason"
        ") VALUES (%s, 'steering', %s, %s, %s, %s)",
        (
            session_id,
            make_steering_target(1).scope_json(),
            now,
            now,
            "strategy review",
        ),
    )
    conn.commit()


def insert_document_lock(conn, session_id: str, project_id: int, slug: str) -> None:
    """Lock one strategy document to a session, seeding the document itself.

    ``strategy_doc_claims`` carries a foreign key onto ``strategy_docs``,
    so a lock cannot exist without the document it locks.
    """
    conn.execute(
        "INSERT INTO strategy_docs (project_id, slug, updated_at) "
        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (project_id, slug, iso()),
    )
    conn.execute(
        "INSERT INTO strategy_doc_claims ("
        "project_id, strategy_doc_slug, owner_kind, owner_session_id, "
        "registered_at"
        ") VALUES (%s, %s, 'session', %s, %s)",
        (project_id, slug, session_id, iso()),
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
    released_at: str | None = None,
) -> None:
    """Seed one shared-operation coordination claim by its operator key.

    The key decides the kind: migration territory is always item-owned,
    a physical host is always session-held.
    """
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
            iso(),
            iso(),
            released_at,
            "completed" if released_at else None,
        ),
    )
    conn.commit()


__all__ = [
    "insert_document_lock",
    "insert_item_claim",
    "insert_lease",
    "insert_session",
    "insert_steering_claim",
    "iso",
]
