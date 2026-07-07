"""Writer/reader coverage for item_status_transitions + item_activity_days."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import item_activity, item_status_transitions
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def db_path(tmp_path: Path):
    with init_test_db(tmp_path) as path:
        yield path


def _seed_item(conn, item_id: int, *, project_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO items (id, title, type, status, created_at, updated_at, "
        "project_id, project_sequence) "
        "VALUES (%s, %s, 'issue', 'idea', '2026-01-01T00:00:00Z', "
        "'2026-01-01T00:00:00Z', %s, %s)",
        (item_id, f"item-{item_id}", project_id, item_id),
    )
    conn.commit()


class TestRecordItemTransition:
    def test_records_row_and_touches_activity(self, db_path):
        conn = connect_test_db(db_path)
        try:
            _seed_item(conn, 41)
            ok = item_status_transitions.record_item_transition(
                conn,
                item_id=41,
                from_status="idea",
                to_status="refining-idea",
                source="backlog-registry",
            )
            conn.commit()
            assert ok is True
            row = conn.execute(
                "SELECT item_id, task_num, from_status, to_status, source, "
                "project_id FROM item_status_transitions"
            ).fetchone()
            assert tuple(row) == (
                41, None, "idea", "refining-idea", "backlog-registry", 1,
            )
            day_row = conn.execute(
                "SELECT project_id, item_id FROM item_activity_days"
            ).fetchone()
            assert tuple(day_row) == (1, 41)
        finally:
            conn.close()

    def test_accepts_sun_prefixed_ref(self, db_path):
        conn = connect_test_db(db_path)
        try:
            _seed_item(conn, 42)
            assert item_status_transitions.record_item_transition(
                conn, item_id="YOK-42", from_status=None, to_status="done",
            )
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM item_status_transitions "
                "WHERE item_id = 42 AND to_status = 'done'"
            ).fetchone()[0]
            assert int(count) == 1
        finally:
            conn.close()

    def test_missing_table_never_poisons_caller_txn(self, db_path):
        conn = connect_test_db(db_path)
        try:
            _seed_item(conn, 43)
            conn.execute("DROP TABLE item_status_transitions")
            conn.commit()
            conn.execute(
                "UPDATE items SET status = 'done' WHERE id = %s", (43,),
            )
            ok = item_status_transitions.record_item_transition(
                conn, item_id=43, from_status="idea", to_status="done",
            )
            conn.commit()  # caller txn must still commit cleanly
            assert ok is False
            status = conn.execute(
                "SELECT status FROM items WHERE id = %s", (43,),
            ).fetchone()[0]
            assert status == "done"
        finally:
            conn.close()


class TestRecordTaskTransition:
    def test_records_task_row_with_epic_item_id(self, db_path):
        conn = connect_test_db(db_path)
        try:
            _seed_item(conn, 44)
            ok = item_status_transitions.record_task_transition(
                conn,
                epic_id="44",
                task_num=3,
                from_status="pending",
                to_status="implementing",
                source="update-status",
            )
            conn.commit()
            assert ok is True
            row = conn.execute(
                "SELECT item_id, task_num, to_status FROM item_status_transitions"
            ).fetchone()
            assert tuple(row) == (44, 3, "implementing")
        finally:
            conn.close()


class TestLatestTransition:
    def test_returns_latest_row(self, db_path):
        conn = connect_test_db(db_path)
        try:
            _seed_item(conn, 45)
            for to_status in ("refining-idea", "refined-idea"):
                item_status_transitions.record_item_transition(
                    conn, item_id=45, from_status=None, to_status=to_status,
                )
            conn.commit()
            latest = item_status_transitions.latest_transition(conn, 45)
            assert latest is not None
            assert latest["to_status"] == "refined-idea"
        finally:
            conn.close()

    def test_returns_none_without_rows_or_table(self, db_path):
        conn = connect_test_db(db_path)
        try:
            assert item_status_transitions.latest_transition(conn, 999) is None
            conn.execute("DROP TABLE item_status_transitions")
            conn.commit()
            assert item_status_transitions.latest_transition(conn, 999) is None
        finally:
            conn.close()


class TestTouchItemActivity:
    def test_same_day_touches_collapse(self, db_path):
        conn = connect_test_db(db_path)
        try:
            _seed_item(conn, 46)
            for _ in range(2):
                assert item_activity.touch_item_activity(conn, item_id=46)
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM item_activity_days WHERE item_id = 46"
            ).fetchone()[0]
            assert int(count) == 1
        finally:
            conn.close()

    def test_unknown_item_is_noop(self, db_path):
        conn = connect_test_db(db_path)
        try:
            assert item_activity.touch_item_activity(conn, item_id=4242) is False
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM item_activity_days"
            ).fetchone()[0]
            assert int(count) == 0
        finally:
            conn.close()

    def test_qa_requirement_touch_resolves_epic_target(self, db_path):
        conn = connect_test_db(db_path)
        try:
            _seed_item(conn, 47)
            conn.execute(
                "INSERT INTO qa_requirements (epic_id, task_num, qa_kind, "
                "qa_phase, created_at) VALUES (%s, %s, 'ac_verification', "
                "'verification', '2026-01-01T00:00:00Z') RETURNING id",
                (47, 1),
            )
            req_id = conn.execute(
                "SELECT MAX(id) FROM qa_requirements"
            ).fetchone()[0]
            assert item_activity.touch_for_qa_requirement(conn, req_id) is True
            conn.commit()
            row = conn.execute(
                "SELECT item_id FROM item_activity_days"
            ).fetchone()
            assert int(row[0]) == 47
        finally:
            conn.close()
