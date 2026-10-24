"""A body slice of a stored item section whose entries carry '## ' headings names the stored read."""

from __future__ import annotations

import io
from pathlib import Path

from yoke_core.domain import render_body
from yoke_core.domain.handlers.reads import _items_get_section
from yoke_core.domain.progress_log import format_entry
from runtime.api.domain.render_body_test_helpers import _connect, _init_db, _p, _seed_item


def _seed_progress_log(conn, item_id: int) -> None:
    p = _p(conn)
    entry = format_entry(timestamp="2026-10-24T16:00:00Z", headline="checkpoint", body="Next: verify.")
    conn.execute(
        "INSERT INTO item_sections (item_id, section_name, content, ordering, source, created_at, updated_at) "
        f"VALUES ({p}, 'Progress Log', {p}, 200, 'agent', '2026-10-24T16:00:00Z', '2026-10-24T16:00:00Z')",
        (item_id, entry),
    )
    conn.commit()


def test_body_section_read_of_progress_log_names_section_get(tmp_path: Path) -> None:
    with _init_db(tmp_path) as db_path:
        conn = _connect(db_path)
        _seed_item(conn, 31, "Progress item")
        _seed_progress_log(conn, 31)
        conn.close()

        out, err = io.StringIO(), io.StringIO()
        rc = render_body.render_section(31, "Progress Log", db_path=db_path, out=out, err=err)
        assert rc == 1
        assert out.getvalue() == ""
        assert "item_section_read_required" in err.getvalue()
        assert "yoke items section get" in err.getvalue()
        assert "--section 'Progress Log'" in err.getvalue()

        outcome = _items_get_section(31, ["body"], "## Progress Log")
        assert outcome.primary_success is False
        assert outcome.error.code == "item_section_read_required"
        assert "yoke items section get" in outcome.error.message


def test_body_section_with_extractable_content_still_reads(tmp_path: Path) -> None:
    with _init_db(tmp_path) as db_path:
        conn = _connect(db_path)
        _seed_item(conn, 32, "Plain section item")
        p = _p(conn)
        conn.execute(
            "INSERT INTO item_sections (item_id, section_name, content, ordering, source, created_at, updated_at) "
            f"VALUES ({p}, 'Notes', 'Plain note.', 100, 'agent', '2026-10-24T16:00:00Z', '2026-10-24T16:00:00Z')",
            (32,),
        )
        conn.commit()
        conn.close()

        outcome = _items_get_section(32, ["body"], "Notes")
        assert outcome.primary_success is True
        assert outcome.result_payload["content"] == "Plain note."
