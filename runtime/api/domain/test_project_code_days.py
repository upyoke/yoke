"""Tests for project_code_days rollup helpers."""

from __future__ import annotations

from yoke_contracts.board.widgets_commit_cache import aggregate_cache_for_projects
from yoke_core.domain.project_code_days import (
    ensure_schema,
    lines_by_day,
    upsert_days,
)


def test_aggregate_cache_for_projects_sums_lines_and_commits():
    cache = {
        "aaa": {"day": "2026-08-01", "lines": 10, "repo": "/r/yoke"},
        "bbb": {"day": "2026-08-01", "lines": 5, "repo": "/r/yoke"},
        "ccc": {"day": "2026-08-02", "lines": 3, "repo": "/r/other"},
    }
    rows = aggregate_cache_for_projects(cache, {"/r/yoke": 1, "/r/other": 2})
    by_key = {(r["project_id"], r["day"]): r for r in rows}
    assert by_key[(1, "2026-08-01")]["commit_count"] == 2
    assert by_key[(1, "2026-08-01")]["lines_changed"] == 15
    assert by_key[(2, "2026-08-02")]["commit_count"] == 1
    assert by_key[(2, "2026-08-02")]["lines_changed"] == 3


def test_upsert_and_lines_by_day(test_db):
    ensure_schema(test_db)
    upsert_days(
        test_db,
        [
            {
                "project_id": 1,
                "day": "2026-08-01",
                "commit_count": 2,
                "lines_changed": 40,
            },
            {
                "project_id": 1,
                "day": "2026-08-02",
                "commit_count": 1,
                "lines_changed": 7,
            },
        ],
    )
    test_db.commit()
    assert lines_by_day(test_db, [1], start_day="2026-08-01") == {
        "2026-08-01": 40,
        "2026-08-02": 7,
    }
