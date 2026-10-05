"""Backlog field updates preserve unrelated item state."""

from runtime.api.backlog_mutations_test_helpers import insert_item
from yoke_core.domain import backlog
from runtime.api.test_backlog_mutations_create import _p


class TestUpdateItemField:
    def test_update_string_field(self, test_db):
        insert_item(test_db, id=10, title="Old")
        backlog._update_item_field(test_db, 10, "title", "New")
        p = _p(test_db)
        row = test_db.execute(f"SELECT title FROM items WHERE id={p}", (10,)).fetchone()
        assert row[0] == "New"

    def test_update_null(self, test_db):
        insert_item(test_db, id=10, blocked_reason="waiting")
        backlog._update_item_field(test_db, 10, "blocked_reason", None)
        p = _p(test_db)
        row = test_db.execute(
            f"SELECT blocked_reason FROM items WHERE id={p}", (10,)
        ).fetchone()
        assert row[0] is None

    def test_update_boolean_field(self, test_db):
        insert_item(test_db, id=10)
        backlog._update_item_field(test_db, 10, "frozen", True)
        p = _p(test_db)
        row = test_db.execute(
            f"SELECT frozen FROM items WHERE id={p}", (10,)
        ).fetchone()
        assert row[0] == 1


class TestUpdateItemMulti:
    def test_multi_field_update(self, test_db):
        insert_item(test_db, id=10, status="idea", priority="low")
        backlog._update_item_multi(
            test_db,
            10,
            {
                "status": "implementing",
                "priority": "high",
            },
        )
        p = _p(test_db)
        row = test_db.execute(
            f"SELECT status, priority FROM items WHERE id={p}", (10,)
        ).fetchone()
        assert row[0] == "implementing"
        assert row[1] == "high"

    def test_multi_with_null(self, test_db):
        insert_item(test_db, id=10, blocked_reason="waiting")
        backlog._update_item_multi(
            test_db,
            10,
            {
                "blocked_reason": None,
                "frozen": False,
            },
        )
        p = _p(test_db)
        row = test_db.execute(
            f"SELECT blocked_reason, frozen FROM items WHERE id={p}", (10,)
        ).fetchone()
        assert row[0] is None
        assert row[1] == 0
