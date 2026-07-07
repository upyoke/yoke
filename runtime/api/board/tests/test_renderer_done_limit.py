"""Done-section render cap regression tests."""

from __future__ import annotations

from yoke_core.board.renderer import render_board
from runtime.api.fixtures.file_test_db import connect_test_db


def test_done_section_limit_caps_old_done_rows(populated_db, tmp_path):
    conn = connect_test_db(populated_db)
    rows = [
        (10, "Done A", 10, "2025-03-05"),
        (11, "Done B", 11, "2025-03-06"),
        (12, "Done C", 12, "2025-03-07"),
    ]
    for item_id, title, seq, updated_at in rows:
        conn.execute(
            "INSERT INTO items "
            "(id, title, type, priority, status, project_id, "
            "project_sequence, updated_at, created_at)"
            " VALUES (%s, %s, 'issue', 'low', 'done', 1, %s, %s, %s)",
            (item_id, title, seq, updated_at, updated_at),
        )
    conn.commit()
    conn.close()
    cfg = tmp_path / "config"
    cfg.write_text(
        "dashboard_velocity=false\n"
        "dashboard_weather=false\n"
        "dashboard_types=false\n"
        "dashboard_age=false\n"
        "dashboard_badges=false\n"
        "dashboard_recent_sessions=false\n"
        "timeline_widget=never\n"
        "done_section_limit=2\n",
        encoding="utf-8",
    )

    output = render_board(populated_db, "yoke", str(cfg), seed=42)

    assert "### ✅ Done (showing 2 of 4)" in output
    assert "Done C" in output
    assert "Done B" in output
    assert "Done A" not in output
    assert "Done item" not in output
    assert "2 older rows hidden by done_section_limit" in output
