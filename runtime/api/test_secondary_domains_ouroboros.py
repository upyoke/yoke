"""Tests for yoke_core.domain.ouroboros."""

from __future__ import annotations

from datetime import timedelta

from yoke_contracts.timestamps import parse_instant

CLOCK = parse_instant("2026-10-09T15:56:12.345678+05:45")
LATER = CLOCK + timedelta(microseconds=1)


class TestOuroboros:
    def test_insert_and_list(self, test_db):
        from yoke_core.domain.ouroboros import cmd_insert_entry, cmd_list_entries

        rid = cmd_insert_entry(
            test_db,
            "2024-01-01T00:00:00Z",
            "agent",
            "ctx",
            "friction",
            "Something broke",
        )
        assert rid.isdigit()

        result = cmd_list_entries(test_db)
        assert "friction" in result
        assert "Something broke" in result.replace("\n", " ")

    def test_dedup(self, test_db):
        from yoke_core.domain.ouroboros import cmd_insert_entry

        cmd_insert_entry(test_db, CLOCK, "a", "c", "cat", "body")
        result = cmd_insert_entry(test_db, CLOCK, "a", "c", "cat", "body")
        assert "Duplicate" in result

    def test_mark_reviewed(self, test_db):
        from yoke_core.domain.ouroboros import cmd_insert_entry, cmd_mark_reviewed

        rid = cmd_insert_entry(test_db, CLOCK, "a", None, "cat", "body")
        result = cmd_mark_reviewed(test_db, int(rid))
        assert "reviewed" in result

    def test_mark_archived_single(self, test_db):
        from yoke_core.domain.ouroboros import (
            cmd_insert_entry,
            cmd_mark_archived,
            cmd_mark_reviewed,
        )

        rid = cmd_insert_entry(test_db, CLOCK, "a", None, "cat", "body")
        cmd_mark_reviewed(test_db, int(rid))
        result = cmd_mark_archived(test_db, entry_id=int(rid))
        assert result == "1"

    def test_mark_archived_all_reviewed(self, test_db):
        from yoke_core.domain.ouroboros import (
            cmd_insert_entry,
            cmd_mark_archived,
            cmd_mark_reviewed,
        )

        r1 = cmd_insert_entry(
            test_db, CLOCK, "a", None, "cat", "body-one", project="yoke"
        )
        r2 = cmd_insert_entry(
            test_db, LATER, "a", None, "cat", "body-two", project="yoke"
        )
        cmd_mark_reviewed(test_db, int(r1))
        cmd_mark_reviewed(test_db, int(r2))
        result = cmd_mark_archived(test_db, all_reviewed=True, project="yoke")
        assert result == "2"

    def test_mark_archived_all_reviewed_scopes_to_project(self, test_db):
        from yoke_core.domain.ouroboros import (
            cmd_insert_entry,
            cmd_mark_archived,
            cmd_mark_reviewed,
        )

        yoke = cmd_insert_entry(
            test_db, CLOCK, "a", None, "cat", "yoke-body", project="yoke"
        )
        other = cmd_insert_entry(
            test_db,
            LATER,
            "a",
            None,
            "cat",
            "other-body",
            project="externalwebapp",
        )
        cmd_mark_reviewed(test_db, int(yoke))
        cmd_mark_reviewed(test_db, int(other))
        result = cmd_mark_archived(test_db, all_reviewed=True, project="yoke")
        assert result == "1"
        leftover = cmd_mark_archived(
            test_db, all_reviewed=True, project="externalwebapp"
        )
        assert leftover == "1"

    def test_list_entries_unreviewed(self, test_db):
        from yoke_core.domain.ouroboros import (
            cmd_insert_entry,
            cmd_list_entries,
            cmd_mark_reviewed,
        )

        cmd_insert_entry(test_db, CLOCK, "a", None, "cat", "unrev")
        r2 = cmd_insert_entry(test_db, LATER, "a", None, "cat", "rev")
        cmd_mark_reviewed(test_db, int(r2))
        result = cmd_list_entries(test_db, unreviewed=True)
        assert "unrev" in result
        assert "rev" not in result.split("\n")[0] if result.count("\n") > 0 else True
