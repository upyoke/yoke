"""Tests for yoke_core.domain.ouroboros."""
from __future__ import annotations


class TestOuroboros:
    def test_insert_and_list(self, test_db):
        from yoke_core.domain.ouroboros import cmd_insert_entry, cmd_list_entries
        rid = cmd_insert_entry(test_db, "2024-01-01T00:00:00Z", "agent",
                               "ctx", "friction", "Something broke")
        assert rid.isdigit()

        result = cmd_list_entries(test_db)
        assert "friction" in result
        assert "Something broke" in result.replace("\n", " ")

    def test_dedup(self, test_db):
        from yoke_core.domain.ouroboros import cmd_insert_entry
        cmd_insert_entry(test_db, "t1", "a", "c", "cat", "body")
        result = cmd_insert_entry(test_db, "t1", "a", "c", "cat", "body")
        assert "Duplicate" in result

    def test_mark_reviewed(self, test_db):
        from yoke_core.domain.ouroboros import cmd_insert_entry, cmd_mark_reviewed
        rid = cmd_insert_entry(test_db, "t1", "a", None, "cat", "body")
        result = cmd_mark_reviewed(test_db, int(rid))
        assert "reviewed" in result

    def test_mark_archived_single(self, test_db):
        from yoke_core.domain.ouroboros import (
            cmd_insert_entry,
            cmd_mark_archived,
            cmd_mark_reviewed,
        )
        rid = cmd_insert_entry(test_db, "t1", "a", None, "cat", "body")
        cmd_mark_reviewed(test_db, int(rid))
        result = cmd_mark_archived(test_db, entry_id=int(rid))
        assert result == "1"

    def test_mark_archived_all_reviewed(self, test_db):
        from yoke_core.domain.ouroboros import (
            cmd_insert_entry,
            cmd_mark_archived,
            cmd_mark_reviewed,
        )
        r1 = cmd_insert_entry(test_db, "t1", "a", None, "cat", "body-one")
        r2 = cmd_insert_entry(test_db, "t2", "a", None, "cat", "body-two")
        cmd_mark_reviewed(test_db, int(r1))
        cmd_mark_reviewed(test_db, int(r2))
        result = cmd_mark_archived(test_db, all_reviewed=True)
        assert result == "2"

    def test_insert_wrapup(self, test_db):
        from yoke_core.domain.ouroboros import cmd_insert_wrapup, cmd_list_wrapups
        rid = cmd_insert_wrapup(test_db, "2024-01-01T10:00:00Z", "# Wrapup body")
        assert rid.isdigit()
        result = cmd_list_wrapups(test_db)
        assert "2024-01-01T10:00:00Z" in result

    def test_list_entries_unreviewed(self, test_db):
        from yoke_core.domain.ouroboros import (
            cmd_insert_entry,
            cmd_list_entries,
            cmd_mark_reviewed,
        )
        r1 = cmd_insert_entry(test_db, "t1", "a", None, "cat", "unrev")
        r2 = cmd_insert_entry(test_db, "t2", "a", None, "cat", "rev")
        cmd_mark_reviewed(test_db, int(r2))
        result = cmd_list_entries(test_db, unreviewed=True)
        assert "unrev" in result
        assert "rev" not in result.split("\n")[0] if result.count("\n") > 0 else True
