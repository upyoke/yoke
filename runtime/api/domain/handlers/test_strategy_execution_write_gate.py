"""Handler integration for item-owned strategy-document claims."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers import strategy_docs as doc_handlers
from yoke_core.domain.handlers import strategy_docs_ingest as ingest_handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    SEED_CONTENT,
    SEED_UPDATED_AT,
    build_request,
    ok_emit,
    seed_docs,
    seed_process_claim,
    seed_session,
)
from yoke_core.domain.strategy_docs_header import content_sha256, render_file_text
from yoke_core.domain.strategy_execution import (
    acquire_strategy_doc_claim,
    link_execution_document,
)
from yoke_core.domain.strategy_execution_schema import (
    ensure_strategy_execution_schema,
)


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            ensure_strategy_execution_schema(conn)
            seed_docs(conn)
            _seed_blitz_claim(conn)
        finally:
            conn.close()
        yield db_path


def _seed_blitz_claim(conn) -> None:
    now = iso8601_now()
    version = conn.execute(
        "SELECT current_version_id FROM workflows WHERE id = 'blitz'"
    ).fetchone()
    conn.execute(
        "INSERT INTO items "
        "(id, title, status, priority, created_at, updated_at, source, "
        "project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (2001, 'Execute PAD', 'implementing', 'medium', %s, %s, "
        "'1', 1, 2001, 'blitz', %s)",
        (now, now, version[0]),
    )
    seed_session(conn, "session-blitz")
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, "
        "last_heartbeat) "
        "VALUES ('session-blitz', 'item', 2001, 'exclusive', %s, %s)",
        (now, now),
    )
    conn.commit()
    link_execution_document(
        conn,
        item_id=2001,
        project_id=1,
        slug="PAD",
        actor_id=1,
        session_id="session-blitz",
    )
    acquire_strategy_doc_claim(
        conn,
        item_id=2001,
        session_id="session-blitz",
        actor_id=1,
    )


def _replace_request(session_id: str, base: str, suffix: str):
    return build_request(
        "strategy.doc.replace",
        {
            "slug": "PAD",
            "content": SEED_CONTENT["PAD"] + suffix,
            "base_updated_at": base,
        },
        session_id=session_id,
        actor_id="42",
    )


def _ingest_request(
    session_id: str,
    base: str,
    base_body: str,
    edited_body: str,
):
    rendered = render_file_text("PAD", base, base_body)
    header, _, _ = rendered.partition("\n")
    return build_request(
        "strategy.ingest.run",
        {
            "files": [{
                "slug": "PAD",
                "path": "/tmp/PAD.md",
                "text": header + "\n" + edited_body,
            }],
        },
        session_id=session_id,
        actor_id="42",
    )


def test_document_claim_holder_can_ingest_handoff_without_process_claim(
    tmp_db: str,
) -> None:
    ingested_body = SEED_CONTENT["PAD"] + "replace\ningest\n"
    with patch.object(
        doc_handlers._events, "emit_event", return_value=ok_emit(),
    ):
        replaced = doc_handlers.handle_doc_replace(
            _replace_request("session-blitz", SEED_UPDATED_AT, "replace\n")
        )
        assert replaced.primary_success is True
        ingested = ingest_handlers.handle_ingest(
            _ingest_request(
                "session-blitz",
                replaced.result_payload["updated_at"],
                SEED_CONTENT["PAD"] + "replace\n",
                ingested_body,
            )
        )
    assert ingested.primary_success is True
    assert ingested.result_payload["docs"][0]["content_sha256"] == (
        content_sha256(ingested_body)
    )
    conn = connect_test_db(tmp_db)
    try:
        sessions = [
            str(row["session_id"])
            for row in conn.execute(
                "SELECT session_id FROM strategy_doc_revisions "
                "WHERE project_id = 1 AND slug = 'PAD' ORDER BY revision"
            ).fetchall()
        ]
    finally:
        conn.close()
    assert sessions == ["session-blitz", "session-blitz"]


def test_caller_without_document_claim_is_refused_even_with_process_claim(
    tmp_db: str,
) -> None:
    conn = connect_test_db(tmp_db)
    try:
        seed_session(conn, "session-outsider")
        seed_process_claim(conn, "session-outsider")
    finally:
        conn.close()
    replaced = doc_handlers.handle_doc_replace(
        _replace_request("session-outsider", SEED_UPDATED_AT, "outsider\n")
    )
    ingested = ingest_handlers.handle_ingest(
        _ingest_request(
            "session-outsider",
            SEED_UPDATED_AT,
            SEED_CONTENT["PAD"],
            SEED_CONTENT["PAD"] + "outsider\n",
        )
    )
    assert replaced.primary_success is False
    assert replaced.error.code == "strategy_document_claim_denied"
    assert ingested.primary_success is False
    assert ingested.error.code == "strategy_document_claim_denied"
