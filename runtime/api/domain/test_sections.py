"""Tests for ``yoke_core.domain.sections`` — core API (upsert/get/list/delete).

Original module covered every flavor of sections behavior. It is now split
across sibling files so each authored file stays under the 350-line limit:
this file covers the core API; CLI surfaces live in ``test_sections_cli`` and
the main-dispatcher / event-fallback coverage lives in ``test_sections_main``.
Heavy fixture/helper code lives in ``sections_test_helpers``.
"""

from __future__ import annotations

from yoke_core.domain import sections
from yoke_core.domain.sections_test_helpers import (  # noqa: F401 — fixtures
    _reset_injectables,
    db_path,
)
from runtime.api.fixtures.file_test_db import connect_test_db


class TestUpsertSection:
    def test_insert_new_row_without_source_uses_default(self, db_path: str) -> None:
        sections.upsert_section(42, "Design", "design body", db_path=db_path)
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT content, ordering, source FROM item_sections "
            "WHERE item_id=42 AND section_name='Design'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "design body"
        assert row[1] is None
        assert row[2] == "operator"

    def test_insert_new_row_with_ordering_and_source(self, db_path: str) -> None:
        sections.upsert_section(
            42, "Design", "body", ordering=10, source="shepherd", db_path=db_path
        )
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT content, ordering, source FROM item_sections "
            "WHERE item_id=42 AND section_name='Design'"
        ).fetchone()
        conn.close()
        assert (row[0], row[1], row[2]) == ("body", 10, "shepherd")

    def test_update_preserves_ordering_when_none_passed(self, db_path: str) -> None:
        sections.upsert_section(42, "Design", "first", ordering=5, db_path=db_path)
        sections.upsert_section(42, "Design", "second", db_path=db_path)
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT content, ordering FROM item_sections "
            "WHERE item_id=42 AND section_name='Design'"
        ).fetchone()
        conn.close()
        assert (row[0], row[1]) == ("second", 5)

    def test_update_overwrites_ordering_when_provided(self, db_path: str) -> None:
        sections.upsert_section(42, "Design", "first", ordering=5, db_path=db_path)
        sections.upsert_section(42, "Design", "second", ordering=9, db_path=db_path)
        conn = connect_test_db(db_path)
        ordering = conn.execute(
            "SELECT ordering FROM item_sections "
            "WHERE item_id=42 AND section_name='Design'"
        ).fetchone()[0]
        conn.close()
        assert ordering == 9

    def test_update_with_source_overwrites_source(self, db_path: str) -> None:
        sections.upsert_section(42, "Design", "a", db_path=db_path)
        sections.upsert_section(
            42, "Design", "b", source="architect", db_path=db_path
        )
        conn = connect_test_db(db_path)
        source = conn.execute(
            "SELECT source FROM item_sections "
            "WHERE item_id=42 AND section_name='Design'"
        ).fetchone()[0]
        conn.close()
        assert source == "architect"

    def test_multiline_content_round_trip(self, db_path: str) -> None:
        content = "Line 1\nLine 2\n\nLine 4 with 'quotes'\n"
        sections.upsert_section(42, "Notes", content, db_path=db_path)
        assert sections.get_section(42, "Notes", db_path=db_path) == content


class TestGetSection:
    def test_missing_row_returns_none(self, db_path: str) -> None:
        assert sections.get_section(42, "Nope", db_path=db_path) is None

    def test_existing_row_returns_content(self, db_path: str) -> None:
        sections.upsert_section(42, "X", "hello", db_path=db_path)
        assert sections.get_section(42, "X", db_path=db_path) == "hello"

    def test_empty_content_row_returns_empty_string(self, db_path: str) -> None:
        sections.upsert_section(42, "Empty", "", db_path=db_path)
        assert sections.get_section(42, "Empty", db_path=db_path) == ""


class TestListSections:
    def test_empty_item_returns_empty_list(self, db_path: str) -> None:
        assert sections.list_sections(42, db_path=db_path) == []

    def test_ordering_null_pushed_to_end(self, db_path: str) -> None:
        sections.upsert_section(42, "B", "b", ordering=1, db_path=db_path)
        sections.upsert_section(42, "A", "a", db_path=db_path)  # ordering=NULL
        sections.upsert_section(42, "C", "c", ordering=2, db_path=db_path)
        rows = sections.list_sections(42, db_path=db_path)
        names = [row[0] for row in rows]
        assert names == ["B", "C", "A"]

    def test_ordering_column_stringified(self, db_path: str) -> None:
        sections.upsert_section(42, "X", "x", ordering=7, db_path=db_path)
        sections.upsert_section(42, "Y", "y", db_path=db_path)
        rows = sections.list_sections(42, db_path=db_path)
        mapping = {row[0]: row[1] for row in rows}
        assert mapping["X"] == "7"
        assert mapping["Y"] == ""

    def test_includes_timestamps(self, db_path: str) -> None:
        sections.upsert_section(42, "X", "x", db_path=db_path)
        rows = sections.list_sections(42, db_path=db_path)
        assert len(rows) == 1
        _name, _ordering, created_at, updated_at = rows[0]
        assert created_at  # non-empty ISO8601
        assert updated_at


class TestDeleteSection:
    def test_delete_removes_row(self, db_path: str) -> None:
        sections.upsert_section(42, "Gone", "x", db_path=db_path)
        sections.delete_section(42, "Gone", db_path=db_path)
        assert sections.get_section(42, "Gone", db_path=db_path) is None

    def test_delete_missing_is_noop(self, db_path: str) -> None:
        # Shell behavior: DELETE on missing row exits 0, prints "Deleted …".
        sections.delete_section(42, "Nope", db_path=db_path)


# ---------------------------------------------------------------------------
# Section CLI paths wire body sync after a successful render
# ---------------------------------------------------------------------------


class TestSectionCliBodySyncWiring:
    """The direct ``sections upsert`` / ``sections delete`` CLI paths must
    share the same post-render body-sync helper that ``items.section.*``
    handlers and ``item_field_transform`` section transforms use. Each path
    routes through :func:`sections.sync_body_after_section_mutation`; this
    test pins the wiring at the CLI surface."""

    def test_cmd_upsert_calls_sync_helper(
        self, db_path: str, tmp_path,
    ) -> None:
        import io
        from unittest.mock import patch
        from yoke_core.domain import sections_cli

        content_file = tmp_path / "content.txt"
        content_file.write_text("body content\n")
        calls: list[tuple] = []

        def fake_sync(item_id, operation):
            calls.append((item_id, operation))
            return True, ""

        out = io.StringIO()
        err = io.StringIO()
        with patch.object(
            sections, "sync_body_after_section_mutation",
            side_effect=fake_sync,
        ):
            rc = sections_cli.cmd_upsert(
                ["42", "Notes", "--content-file", str(content_file)],
                db_path=db_path, out=out, err=err,
            )
        assert rc == 0
        assert calls == [(42, "upsert")]

    def test_cmd_delete_calls_sync_helper(
        self, db_path: str,
    ) -> None:
        import io
        from unittest.mock import patch
        from yoke_core.domain import sections_cli

        sections.upsert_section(42, "Stale", "x", db_path=db_path)
        calls: list[tuple] = []

        def fake_sync(item_id, operation):
            calls.append((item_id, operation))
            return True, ""

        out = io.StringIO()
        err = io.StringIO()
        with patch.object(
            sections, "sync_body_after_section_mutation",
            side_effect=fake_sync,
        ):
            rc = sections_cli.cmd_delete(
                ["42", "Stale"], db_path=db_path, out=out, err=err,
            )
        assert rc == 0
        assert calls == [(42, "delete")]

    def test_cmd_upsert_surfaces_degraded_warning_to_stderr(
        self, db_path: str, tmp_path,
    ) -> None:
        import io
        from unittest.mock import patch
        from yoke_core.domain import sections_cli

        content_file = tmp_path / "content.txt"
        content_file.write_text("body content\n")

        out = io.StringIO()
        err = io.StringIO()
        with patch.object(
            sections, "sync_body_after_section_mutation",
            return_value=(False, "section upsert: sync_body failed"),
        ):
            rc = sections_cli.cmd_upsert(
                ["42", "Notes", "--content-file", str(content_file)],
                db_path=db_path, out=out, err=err,
            )
        # CLI still exits 0 on a degraded sync — the DB write committed.
        assert rc == 0
        assert "github_sync_degraded" in err.getvalue()
