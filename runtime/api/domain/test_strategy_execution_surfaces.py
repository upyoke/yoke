"""Document-history, ancestry, and Blitz execution-claim contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import strategy_docs
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.strategy_doc_history import (
    diff_doc_revisions,
    list_doc_revisions,
    restore_doc_revision,
)
from yoke_core.domain.strategy_coordination import (
    append_strategy_coordination,
    blitz_completion_evidence,
)
from yoke_core.domain.strategy_doc_surfaces import (
    get_blitz_surface,
    get_strategy_surface,
    list_strategy_surfaces,
    set_strategy_doc_parent,
)
from yoke_core.domain.strategy_docs_create import create_doc
from yoke_core.domain.strategy_execution import (
    StrategyDocClaimAuthorizationError,
    StrategyDocClaimConflictError,
    StrategyExecutionLinkError,
    acquire_strategy_doc_claim,
    authorize_strategy_doc_write,
    link_execution_document,
    release_strategy_doc_claim,
)
from yoke_core.domain.strategy_execution_schema import (
    ensure_strategy_execution_schema,
)
from yoke_core.domain.strategy_review_requests import (
    ensure_current_strategy_revision_review,
)


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            ensure_strategy_execution_schema(conn)
            create_decision_request_tables(conn)
        finally:
            conn.close()
        yield db_path


def _seed_doc(conn, slug: str, content: str) -> dict:
    return create_doc(conn, 1, slug, content, actor_id=1)


def _seed_blitz_item(conn, item_id: int, sequence: int) -> None:
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


def _seed_session_claim(conn, item_id: int, session_id: str) -> None:
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


def _handoff_item_claim(conn, item_id: int, before: str, after: str) -> None:
    now = iso8601_now()
    conn.execute(
        "UPDATE work_claims SET released_at = %s, release_reason = 'handed_off' "
        "WHERE item_id = %s AND session_id = %s AND released_at IS NULL",
        (now, item_id, before),
    )
    _seed_session_claim(conn, item_id, after)


def test_history_diff_and_restore_append_new_revision(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        created = _seed_doc(conn, "EXECUTION-PLAN", "# Plan\n\nfirst\n")
        second = strategy_docs.replace_doc(
            conn,
            1,
            "EXECUTION-PLAN",
            "# Plan\n\nfirst\nsecond\n",
            actor_id=2,
            base_updated_at=created["updated_at"],
        )
        comparison = diff_doc_revisions(conn, 1, "EXECUTION-PLAN", 1, 2)
        restored = restore_doc_revision(
            conn,
            1,
            "EXECUTION-PLAN",
            1,
            base_updated_at=second["updated_at"],
            actor_id=3,
        )
        revisions = list_doc_revisions(conn, 1, "EXECUTION-PLAN")
        current = strategy_docs.get_doc(conn, 1, "EXECUTION-PLAN")
    finally:
        conn.close()

    assert comparison["added_lines"] == 1
    assert "+second" in comparison["diff"]
    assert restored["revision"] == 3
    assert [row["revision"] for row in revisions] == [3, 2, 1]
    assert revisions[0]["source_operation"] == "restore:1"
    assert current["content"] == "# Plan\n\nfirst\n"


def test_current_revision_review_is_nonblocking_and_visible(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, "REVIEW-PLAN", "# Review plan\n")
        request, created = ensure_current_strategy_revision_review(
            conn,
            project_id=1,
            slug="REVIEW-PLAN",
            originator_actor_id=1,
            session_id="strategy-review",
        )
        detail = get_strategy_surface(conn, 1, "REVIEW-PLAN")
    finally:
        conn.close()
    assert created is True
    assert request["blocking"] is False
    assert request["subject_key"] == "1:REVIEW-PLAN:1"
    assert detail["pending_review_count"] == 1


def test_single_parent_rejects_cycles_and_surfaces_ancestry(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, "PARENT", "# Parent\n")
        _seed_doc(conn, "CHILD", "# Child\n\nPARENT is the plan of record.\n")
        set_strategy_doc_parent(
            conn, project_id=1, slug="CHILD", parent_slug="PARENT",
        )
        conn.execute(
            "INSERT INTO decision_requests "
            "(kind, subject_type, subject_key, project_id, blocking, "
            "status, created_at) "
            "VALUES ('strategy_revision_review', 'strategy_doc_revision', "
            "'1:CHILD:1', 1, 0, 'pending', %s)",
            (iso8601_now(),),
        )
        conn.commit()
        detail = get_strategy_surface(conn, 1, "CHILD")
        corpus = list_strategy_surfaces(conn, 1)
        with pytest.raises(StrategyExecutionLinkError, match="cycle"):
            set_strategy_doc_parent(
                conn, project_id=1, slug="PARENT", parent_slug="CHILD",
            )
    finally:
        conn.close()

    assert detail["parent_slug"] == "PARENT"
    assert detail["references"] == ["PARENT"]
    assert detail["pending_review_count"] == 1
    assert detail["review_requests"][0]["kind"] == "strategy_revision_review"
    child = next(row for row in corpus if row["slug"] == "CHILD")
    assert child["parent_slug"] == "PARENT"
    assert child["revisions"] == 1
    assert child["recent_writes"] == 1


def test_item_owned_claim_survives_session_handoff(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, "LIVE-PLAN", "# Live plan\n")
        _seed_blitz_item(conn, 2001, 2001)
        _seed_session_claim(conn, 2001, "session-a")
        link_execution_document(
            conn,
            item_id=2001,
            project_id=1,
            slug="LIVE-PLAN",
            actor_id=1,
            session_id="session-a",
        )
        claim = acquire_strategy_doc_claim(
            conn, item_id=2001, session_id="session-a", actor_id=1,
        )
        appended = append_strategy_coordination(
            conn,
            project_id=1,
            slug="LIVE-PLAN",
            section="Slice Log",
            entry="- worker session landed a committed slice",
            actor_id=None,
            session_id="worker-session",
        )
        assert authorize_strategy_doc_write(
            conn, project_id=1, slug="LIVE-PLAN", session_id="session-a",
        )
        _handoff_item_claim(conn, 2001, "session-a", "session-b")
        with pytest.raises(StrategyDocClaimAuthorizationError):
            authorize_strategy_doc_write(
                conn, project_id=1, slug="LIVE-PLAN", session_id="session-a",
            )
        assert authorize_strategy_doc_write(
            conn, project_id=1, slug="LIVE-PLAN", session_id="session-b",
        )
        surface = get_blitz_surface(conn, 2001)
        released = release_strategy_doc_claim(
            conn,
            item_id=2001,
            session_id="session-b",
            actor_id=1,
            reason="completed",
        )
    finally:
        conn.close()

    assert claim["owning_item_id"] == 2001
    assert appended["revision"] == 2
    assert surface["execution_document"]["revisions"][0]["session_id"] == (
        "worker-session"
    )
    assert surface["execution_document"]["slug"] == "LIVE-PLAN"
    assert "worker session landed" in surface["execution_document"]["content"]
    assert surface["item_claim"]["session_id"] == "session-b"
    assert released["release_mode"] == "normal"


def test_second_blitz_cannot_claim_same_document(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, "SHARED-PLAN", "# Shared plan\n")
        for item_id, session_id in ((2001, "session-a"), (2002, "session-b")):
            _seed_blitz_item(conn, item_id, item_id)
            _seed_session_claim(conn, item_id, session_id)
            link_execution_document(
                conn,
                item_id=item_id,
                project_id=1,
                slug="SHARED-PLAN",
                actor_id=1,
                session_id=session_id,
            )
        acquire_strategy_doc_claim(
            conn, item_id=2001, session_id="session-a", actor_id=1,
        )
        with pytest.raises(StrategyDocClaimConflictError, match="item 2001"):
            acquire_strategy_doc_claim(
                conn, item_id=2002, session_id="session-b", actor_id=1,
            )
    finally:
        conn.close()


def test_break_glass_release_requires_reason(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, "STRANDED", "# Stranded\n")
        _seed_blitz_item(conn, 2001, 2001)
        _seed_session_claim(conn, 2001, "session-a")
        link_execution_document(
            conn,
            item_id=2001,
            project_id=1,
            slug="STRANDED",
            actor_id=1,
            session_id="session-a",
        )
        acquire_strategy_doc_claim(
            conn, item_id=2001, session_id="session-a", actor_id=1,
        )
        with pytest.raises(StrategyDocClaimAuthorizationError, match="reason"):
            release_strategy_doc_claim(
                conn,
                item_id=2001,
                session_id="operator",
                actor_id=9,
                break_glass=True,
            )
        result = release_strategy_doc_claim(
            conn,
            item_id=2001,
            session_id="operator",
            actor_id=9,
            break_glass=True,
            reason="holder machine was lost",
        )
    finally:
        conn.close()
    assert result["release_mode"] == "break_glass"


def test_blitz_completion_evidence_stays_in_the_document(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(
            conn,
            "CLOSEOUT",
            "# Closeout\n\n## Completion and parent reconciliation\n\n"
            "Completed the work. Verification evidence is recorded. "
            "No remaining work; the parent was reconciled.\n",
        )
        _seed_blitz_item(conn, 2001, 2001)
        link_execution_document(
            conn,
            item_id=2001,
            project_id=1,
            slug="CLOSEOUT",
            actor_id=1,
            session_id="session-a",
        )
        evidence = blitz_completion_evidence(conn, 2001)
    finally:
        conn.close()
    assert evidence["satisfied"] is True
    assert evidence["missing"] == []
