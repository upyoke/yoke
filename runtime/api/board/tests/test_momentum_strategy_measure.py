"""The strategy momentum series measured against saved revisions.

The figure both momentum surfaces render is a product work metric, so it
must not shrink when telemetry ages out. These cases run the real query
against Postgres with the ``events`` table emptied, which is what a
universe past its event retention window looks like.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.board.momentum_series import strategy_bytes_by_day
from yoke_core.domain.board_zen_signals import ConnBoardDB
from yoke_core.domain.strategy_docs_schema import (
    STRATEGY_DOC_REVISIONS_TABLE,
    record_doc_revision,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

PROJECT = 1
DAY = "2026-08-14"
OTHER_DAY = "2026-08-15"


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _save(conn, slug: str, content: str, *, day: str = DAY) -> None:
    record_doc_revision(
        conn,
        PROJECT,
        slug,
        content,
        source_operation="replace",
        actor_id=None,
        created_at=f"{day}T09:00:00Z",
    )


def _drop_all_events(conn) -> None:
    """Stand in for a universe whose retention window has passed."""
    conn.execute("DELETE FROM events")
    conn.commit()


def _series(conn) -> dict:
    return strategy_bytes_by_day(ConnBoardDB(conn), [PROJECT], days=120)


def test_size_change_survives_an_empty_events_table(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _save(conn, "MISSION", "a" * 100)
        _save(conn, "MISSION", "a" * 130)
        _save(conn, "MISSION", "a" * 120)
        conn.commit()
        _drop_all_events(conn)
        series = _series(conn)
    finally:
        conn.close()
    # 100 authored, then +30, then -10 — the whole first save plus each
    # adjacent move, not three whole copies of the document.
    assert series == {DAY: 140}


def test_a_repeated_identical_save_adds_nothing(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _save(conn, "MISSION", "a" * 100)
        for _ in range(20):
            _save(conn, "MISSION", "a" * 100)
        conn.commit()
        _drop_all_events(conn)
        series = _series(conn)
    finally:
        conn.close()
    # Summing byte_length would report twenty-one whole copies here.
    assert series == {DAY: 100}


def test_each_document_is_measured_against_its_own_history(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _save(conn, "MISSION", "a" * 100)
        _save(conn, "VISION", "b" * 40)
        _save(conn, "MISSION", "a" * 110)
        _save(conn, "VISION", "b" * 45)
        conn.commit()
        _drop_all_events(conn)
        series = _series(conn)
    finally:
        conn.close()
    assert series == {DAY: 100 + 40 + 10 + 5}


def test_days_are_measured_across_the_boundary_between_them(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _save(conn, "MISSION", "a" * 100, day=DAY)
        _save(conn, "MISSION", "a" * 175, day=OTHER_DAY)
        conn.commit()
        _drop_all_events(conn)
        series = _series(conn)
    finally:
        conn.close()
    assert series == {DAY: 100, OTHER_DAY: 75}


def test_a_document_with_no_knowable_baseline_is_excluded(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        # An imported corpus whose earliest saved revision is not its
        # first: the size it started at is unknown, so counting the whole
        # document would invent authoring that day.
        for revision, size in ((7, 500), (8, 530)):
            conn.execute(
                f"INSERT INTO {STRATEGY_DOC_REVISIONS_TABLE} "
                "(project_id, slug, revision, content, content_sha256, "
                "byte_length, source_operation, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    PROJECT, "IMPORTED", revision, "c" * size,
                    f"sha-{revision}", size, "replace", f"{DAY}T09:00:00Z",
                ),
            )
        conn.commit()
        _drop_all_events(conn)
        series = _series(conn)
    finally:
        conn.close()
    # Only the one move between the two retained revisions is knowable.
    assert series == {DAY: 30}


def test_both_meter_paths_report_the_same_figure(tmp_db: str) -> None:
    from yoke_contracts.board.widgets_velocity_meter import _legacy_series

    conn = connect_test_db(tmp_db)
    try:
        _save(conn, "MISSION", "a" * 100)
        _save(conn, "MISSION", "a" * 130)
        conn.commit()
        _drop_all_events(conn)
        db = ConnBoardDB(conn)
        shared = strategy_bytes_by_day(db, [PROJECT], days=120)
        *_, legacy = _legacy_series(db, "", [PROJECT], 120, [])
    finally:
        conn.close()
    assert shared == legacy == {DAY: 130}
