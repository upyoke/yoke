"""Crash recovery for field-note to Dash promotion."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.field_note_dash_promotion import (
    FieldNotePromotionError,
    FieldNotePromotionInProgress,
    ensure_field_note_dash_promotion_schema,
    promote_field_note_to_dash,
)
from yoke_core.domain.field_note_dash_promotion_reads import (
    source_field_note_for_dash,
)
from yoke_core.domain.field_note_dash_promotion_recovery import (
    persist_completed_promotion,
    release_promotion_reservation,
    try_hold_promotion_reservation,
)

ENTRY_ID = 22990
TITLE = "Recover interrupted promotion"


@contextmanager
def _peer_connection():
    conn = db_backend.connect_psycopg(db_backend.resolve_pg_dsn())
    try:
        yield conn
    finally:
        conn.close()


def _seed_note(conn) -> None:
    ensure_field_note_dash_promotion_schema(conn)
    conn.execute(
        "INSERT INTO ouroboros_entries "
        "(id, timestamp, agent, category, body, created_at, project_id) "
        "VALUES (%s, '2026-08-20T00:00:00Z', 'codex', "
        "'field-note-observation', 'Promotion must survive a crash.', "
        "'2026-08-20T00:00:00Z', 1)",
        (ENTRY_ID,),
    )
    conn.commit()


def _promote(conn, **kwargs):
    payload = dict(
        entry_id=ENTRY_ID,
        title=TITLE,
        instruction=None,
        project=None,
        priority=None,
        workflow_posture=None,
        actor_id=1,
        session_id="session-crash",
    )
    payload.update(kwargs)
    return promote_field_note_to_dash(conn, **payload)


def _patch_create(monkeypatch, conn, *, crash=None):
    from yoke_core.domain import backlog_create_op

    calls: list[dict] = []

    def _create(**kwargs):
        calls.append(kwargs)
        if crash == "after_reservation" and len(calls) == 1:
            raise RuntimeError("injected crash after reservation")
        item_id = 2500 + len(calls)
        insert_item(conn, id=item_id, workflow_id="dash", title=kwargs["title"])
        if crash == "after_create" and len(calls) == 1:
            raise RuntimeError("injected crash after item creation")
        return {"success": True, "item_id": item_id, "item_ref": f"YOK-{item_id}"}

    monkeypatch.setattr(backlog_create_op, "execute_create", _create)
    return calls


def _dash_ids(conn) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM items WHERE workflow_id = %s ORDER BY id",
        ("dash",),
    ).fetchall()
    return [int(row[0] if not hasattr(row, "keys") else row["id"]) for row in rows]


def test_retry_after_crash_after_reservation_creates_once(test_db, monkeypatch):
    _seed_note(test_db)
    calls = _patch_create(monkeypatch, test_db, crash="after_reservation")

    with pytest.raises(RuntimeError, match="after reservation"):
        _promote(test_db)
    recovered = _promote(test_db)

    assert recovered.created is True
    assert recovered.dash_item_id == 2502
    assert calls[0]["entry_surface"] == "promotion"
    assert len(calls) == 2
    assert _dash_ids(test_db) == [2502]


def test_retry_after_crash_after_create_links_existing_dash(test_db, monkeypatch):
    _seed_note(test_db)
    calls = _patch_create(monkeypatch, test_db, crash="after_create")

    with pytest.raises(RuntimeError, match="after item creation"):
        _promote(test_db)
    recovered = _promote(test_db)

    assert recovered.created is False
    assert recovered.dash_item_id == 2501
    assert len(calls) == 1
    assert _dash_ids(test_db) == [2501]
    assert source_field_note_for_dash(test_db, 2501)["entry_id"] == ENTRY_ID


def test_retry_after_crash_after_linking_returns_completed(test_db, monkeypatch):
    _seed_note(test_db)
    calls = _patch_create(monkeypatch, test_db)
    real_persist = persist_completed_promotion

    def _persist(conn, **kwargs):
        real_persist(conn, **kwargs)
        raise RuntimeError("injected crash after linking")

    monkeypatch.setattr(
        "yoke_core.domain.field_note_dash_promotion.persist_completed_promotion",
        _persist,
    )
    with pytest.raises(RuntimeError, match="after linking"):
        _promote(test_db)
    recovered = _promote(test_db)

    assert recovered.created is False
    assert recovered.dash_item_id == 2501
    assert len(calls) == 1
    assert _dash_ids(test_db) == [2501]


def test_concurrent_caller_is_in_progress_while_reservation_is_held(
    test_db, monkeypatch,
):
    _seed_note(test_db)
    calls = _patch_create(monkeypatch, test_db)
    assert try_hold_promotion_reservation(test_db, ENTRY_ID)
    try:
        with _peer_connection() as peer:
            with pytest.raises(FieldNotePromotionInProgress):
                _promote(peer)
        assert calls == []
        assert _dash_ids(test_db) == []
    finally:
        release_promotion_reservation(test_db, ENTRY_ID)
    created = _promote(test_db)
    assert created.created is True
    assert created.dash_item_id == 2501


def test_completed_promotion_does_not_create_again(test_db, monkeypatch):
    _seed_note(test_db)
    calls = _patch_create(monkeypatch, test_db)
    first = _promote(test_db)
    second = _promote(test_db, title="Ignored repeat title")

    assert first.created is True
    assert second.created is False
    assert second.dash_item_id == first.dash_item_id == 2501
    assert len(calls) == 1
    assert _dash_ids(test_db) == [2501]


def test_explicit_failed_retry_creates_the_dash(test_db, monkeypatch):
    _seed_note(test_db)
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO ouroboros_entry_dispositions "
        "(entry_id, disposition_kind, state, title, instruction, "
        "failure_reason, created_at, updated_at) "
        "VALUES (%s, 'promote_to_dash', 'failed', 'Old title', "
        "'Old instruction', 'Dash creation failed', %s, %s)",
        (ENTRY_ID, now, now),
    )
    test_db.commit()
    calls = _patch_create(monkeypatch, test_db)

    recovered = _promote(test_db)
    assert recovered.created is True
    assert recovered.dash_item_id == 2501
    assert len(calls) == 1
    assert calls[0]["title"] == TITLE


def test_create_failure_marks_failed_and_refuses(test_db, monkeypatch):
    _seed_note(test_db)
    from yoke_core.domain import backlog_create_op

    monkeypatch.setattr(
        backlog_create_op,
        "execute_create",
        lambda **_kwargs: {"success": False, "error": "workflow is required"},
    )
    with pytest.raises(FieldNotePromotionError, match="workflow is required"):
        _promote(test_db)
    row = test_db.execute(
        "SELECT state, failure_reason FROM ouroboros_entry_dispositions "
        "WHERE entry_id = %s",
        (ENTRY_ID,),
    ).fetchone()
    assert row[0] == "failed"
    assert row[1] == "workflow is required"
