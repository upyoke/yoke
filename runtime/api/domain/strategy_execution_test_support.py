"""Shared database and record builders for strategy execution tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.strategy_docs_create import create_doc
from yoke_core.domain.strategy_execution_schema import (
    ensure_strategy_execution_schema,
)


@contextmanager
def strategy_test_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            ensure_strategy_execution_schema(conn)
            create_decision_request_tables(conn)
        finally:
            conn.close()
        yield db_path


def seed_strategy_doc(conn, slug: str, content: str) -> dict:
    return create_doc(conn, 1, slug, content, actor_id=1)


def seed_blitz_item(conn, item_id: int, sequence: int) -> None:
    version = conn.execute(
        "SELECT current_version_id FROM workflows WHERE id = 'blitz'"
    ).fetchone()
    now = iso8601_now()
    conn.execute(
        "INSERT INTO items "
        "(id, title, status, priority, created_at, updated_at, source, "
        "project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (%s, %s, 'implementing', 'medium', %s, %s, '1', "
        "1, %s, 'blitz', %s)",
        (item_id, f"Blitz {item_id}", now, now, sequence, version[0]),
    )
    conn.commit()


def seed_session_claim(conn, item_id: int, session_id: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, project_id, "
        "offered_at, last_heartbeat) "
        "VALUES (%s, 'codex', 'openai', 'gpt', '/tmp', 1, %s, %s)",
        (session_id, now, now),
    )
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, "
        "last_heartbeat) VALUES (%s, 'item', %s, 'exclusive', %s, %s)",
        (session_id, item_id, now, now),
    )
    conn.commit()


def seed_session(conn, session_id: str) -> None:
    """Register one harness session with no work claim of its own."""
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, project_id, "
        "offered_at, last_heartbeat) "
        "VALUES (%s, 'codex', 'openai', 'gpt', '/tmp', 1, %s, %s) "
        "ON CONFLICT (session_id) DO NOTHING",
        (session_id, now, now),
    )
    conn.commit()


def link_blitz_document(conn, item_id: int, slug: str) -> None:
    """Bind a Blitz item to the document it executes."""
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) "
        "VALUES (%s, 1, %s, %s)",
        (item_id, slug, iso8601_now()),
    )
    conn.commit()


#: Document-lock test vocabulary shared by the lock and exclusion suites.
COORDINATOR_SESSION = "coordinator-session"
WORKER_SESSION = "worker-session"
LOCKED_DOC = "AREA-PLAN"


def seed_linked_blitz(conn, item_id: int, slug: str = LOCKED_DOC) -> None:
    """Seed a Blitz item already bound to the document it executes."""
    seed_blitz_item(conn, item_id, item_id)
    link_blitz_document(conn, item_id, slug)


def lock_document(
    conn,
    session_id: str = COORDINATOR_SESSION,
    slug: str = LOCKED_DOC,
) -> dict:
    """Take the session-owned lock the way a coordinator would."""
    from yoke_core.domain.strategy_execution import acquire_session_doc_claim

    return acquire_session_doc_claim(
        conn,
        project_id=1,
        slug=slug,
        session_id=session_id,
        actor_id=1,
        reason="shaping the plan",
    )


def strategy_function_request(
    function_id: str,
    *,
    target: TargetRef,
    payload: dict | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(
            session_id="refine-blitz-test",
            actor_id="1",
        ),
        target=target,
        payload=payload or {},
    )


def handoff_item_claim(
    conn,
    item_id: int,
    before: str,
    after: str,
) -> None:
    now = iso8601_now()
    conn.execute(
        "UPDATE work_claims SET released_at = %s, release_reason = 'handed_off' "
        "WHERE item_id = %s AND session_id = %s AND released_at IS NULL",
        (now, item_id, before),
    )
    seed_session_claim(conn, item_id, after)
