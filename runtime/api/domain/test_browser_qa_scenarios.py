"""Tests for the metadata-driven browser scenario helpers in qa_requirements.

Covers:
- ``read_browser_qa_metadata`` returning the negative default for unset rows,
  the validated dict for populated rows, and raising on malformed stored JSON.
- ``build_browser_requirements_from_metadata`` emitting zero requirements for
  non-browser items, one smoke per route, additional timed smokes per
  AC-derived timing hint, optional browser_diff on visual_outcome, and always
  routing every scenario through the settle-delay floor.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain.browser_qa_metadata import (
    BrowserQaMetadataError,
    NEGATIVE_DEFAULT,
    canonical_json,
)
from yoke_core.domain.items import insert_item, update_structured_field
from yoke_core.domain.qa_requirements import (
    DEFAULT_SETTLE_MS,
    build_browser_requirements_from_metadata,
    read_browser_qa_metadata,
)


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as path:
        insert_item(
            item_id=1,
            title="Scenario builder smoke",
            item_type="issue",
            status="refined-idea",
            priority="medium",
            source="user",
            project="yoke",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            db_path=path,
        )
        yield path


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestReadBrowserQaMetadata:
    def test_missing_returns_negative_default(self, db_path):
        result = read_browser_qa_metadata(1, db_path=db_path)
        assert result == NEGATIVE_DEFAULT

    def test_populated_round_trips_validated_form(self, db_path):
        payload = {
            "browser_testable": True,
            "visual_outcome": True,
            "browser_routes": ["/login"],
            "browser_timing_hints_ms": [2000],
        }
        update_structured_field(
            1, "browser_qa_metadata", canonical_json(payload),
            db_path=db_path,
        )
        result = read_browser_qa_metadata(1, db_path=db_path)
        assert result == payload

    def test_stored_null_treated_as_negative_default(self, db_path):
        # Force a legacy NULL by writing directly via a raw DB connection
        # (we skip the validator for this pre-migration simulation).
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE items SET browser_qa_metadata = NULL WHERE id = 1"
        )
        conn.commit()
        conn.close()
        assert read_browser_qa_metadata(1, db_path=db_path) == NEGATIVE_DEFAULT

    def test_stored_literal_null_treated_as_negative_default(self, db_path):
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE items SET browser_qa_metadata = 'null' WHERE id = 1"
        )
        conn.commit()
        conn.close()
        assert read_browser_qa_metadata(1, db_path=db_path) == NEGATIVE_DEFAULT

    def test_malformed_stored_metadata_raises(self, db_path):
        conn = connect_test_db(db_path)
        p = _placeholder(conn)
        conn.execute(
            f"UPDATE items SET browser_qa_metadata = {p} WHERE id = 1",
            ('{"browser_testable": "yes"}',),  # skips required keys + wrong type
        )
        conn.commit()
        conn.close()
        with pytest.raises(BrowserQaMetadataError):
            read_browser_qa_metadata(1, db_path=db_path)


class TestBuildBrowserRequirementsFromMetadata:
    def _write(self, db_path, payload):
        update_structured_field(
            1, "browser_qa_metadata", canonical_json(payload),
            db_path=db_path,
        )

    def test_non_browser_returns_empty(self, db_path):
        self._write(db_path, NEGATIVE_DEFAULT)
        rows = build_browser_requirements_from_metadata(
            1, "https://example.test", db_path=db_path,
        )
        assert rows == []

    def test_single_route_produces_one_smoke_row(self, db_path):
        self._write(db_path, {
            "browser_testable": True,
            "visual_outcome": False,
            "browser_routes": ["/login"],
            "browser_timing_hints_ms": [],
        })
        rows = build_browser_requirements_from_metadata(
            1, "https://example.test", db_path=db_path,
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["qa_kind"] == "browser_smoke"
        assert row["blocking_mode"] == "blocking"
        assert row["requirement_source"] == "seeded_default"
        policy = json.loads(row["success_policy"])
        assert policy["type"] == "browser_scenario"
        assert policy["base_url"] == "https://example.test"
        actions = [step["action"] for step in policy["steps"]]
        assert actions == ["navigate", "delay", "screenshot"]
        delay_step = next(s for s in policy["steps"] if s["action"] == "delay")
        assert delay_step["duration"] == DEFAULT_SETTLE_MS

    def test_multiple_routes_and_timings_split_rows(self, db_path):
        self._write(db_path, {
            "browser_testable": True,
            "visual_outcome": True,
            "browser_routes": ["/forgot-password", "/login"],
            "browser_timing_hints_ms": [7000],
        })
        rows = build_browser_requirements_from_metadata(
            1, "https://example.test", db_path=db_path,
        )
        # 2 routes × (1 base + 1 timed) = 4 rows (diff not requested)
        assert len(rows) == 4
        route_counts = {"/forgot-password": 0, "/login": 0}
        for row in rows:
            policy = json.loads(row["success_policy"])
            nav = next(s for s in policy["steps"] if s["action"] == "navigate")
            route_counts[nav["route"]] += 1
        assert route_counts == {"/forgot-password": 2, "/login": 2}

        # Timed smoke uses the AC-derived 7000 ms hint, not the floor
        timed_rows = [
            json.loads(r["success_policy"]) for r in rows
            if any(s["action"] == "delay" and s.get("duration") == 7000
                   for s in json.loads(r["success_policy"])["steps"])
        ]
        assert len(timed_rows) == 2

    def test_empty_routes_default_to_site_root(self, db_path):
        self._write(db_path, {
            "browser_testable": True,
            "visual_outcome": False,
            "browser_routes": [],
            "browser_timing_hints_ms": [],
        })
        rows = build_browser_requirements_from_metadata(
            1, "https://example.test", db_path=db_path,
        )
        assert len(rows) == 1
        policy = json.loads(rows[0]["success_policy"])
        nav = next(s for s in policy["steps"] if s["action"] == "navigate")
        assert nav["route"] == "/"

    def test_include_diff_adds_browser_diff_when_visual_outcome(self, db_path):
        self._write(db_path, {
            "browser_testable": True,
            "visual_outcome": True,
            "browser_routes": ["/login"],
            "browser_timing_hints_ms": [],
        })
        rows = build_browser_requirements_from_metadata(
            1, "https://example.test",
            db_path=db_path, include_diff=True,
        )
        kinds = sorted(r["qa_kind"] for r in rows)
        assert kinds == ["browser_diff", "browser_smoke"]

    def test_include_diff_skipped_when_visual_outcome_false(self, db_path):
        self._write(db_path, {
            "browser_testable": True,
            "visual_outcome": False,
            "browser_routes": ["/login"],
            "browser_timing_hints_ms": [],
        })
        rows = build_browser_requirements_from_metadata(
            1, "https://example.test",
            db_path=db_path, include_diff=True,
        )
        kinds = [r["qa_kind"] for r in rows]
        assert kinds == ["browser_smoke"]

    def test_requirement_source_override(self, db_path):
        self._write(db_path, {
            "browser_testable": True,
            "visual_outcome": False,
            "browser_routes": ["/"],
            "browser_timing_hints_ms": [],
        })
        rows = build_browser_requirements_from_metadata(
            1, "https://example.test",
            db_path=db_path, requirement_source="ac_derived",
        )
        assert rows[0]["requirement_source"] == "ac_derived"
