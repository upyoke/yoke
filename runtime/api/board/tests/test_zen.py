"""Tests for yoke_contracts.board.zen — zen-scene project timeline widget.

Companion file ``test_zen_labels.py`` covers the label-extraction logic.
This file holds visibility, zone computation, dot positions, VISION.md
parsing, queries, and the integrated render.

Shared fixtures (``zen_db`` and the ``insert_zen_items`` helper) live
in ``conftest.py``.
"""

from __future__ import annotations

import textwrap

from yoke_contracts.board.config import BoardConfig
from yoke_core.board.db import BoardDB
from yoke_contracts.board.zen import (
    _zen_check_visibility,
    _zen_compute_window,
    _zen_compute_zones,
    _zen_extract_vision,
    _zen_item_positions,
    _zen_query_projects,
    _zen_queued_count,
    render_zen_widget,
)

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.board.tests.conftest import insert_zen_items


# -- visibility tests ----------------------------------------------------------

class TestVisibility:
    def test_always_shows(self):
        assert _zen_check_visibility("always", 5, 3, 10) is True

    def test_never_hides(self):
        assert _zen_check_visibility("never", 0, 0, 0) is False

    def test_idle_shows_when_all_zero(self):
        assert _zen_check_visibility("idle", 0, 0, 0) is True

    def test_idle_hides_when_active(self):
        assert _zen_check_visibility("idle", 1, 0, 0) is False

    def test_idle_hides_when_pipeline(self):
        assert _zen_check_visibility("idle", 0, 1, 0) is False

    def test_idle_hides_when_backlog(self):
        assert _zen_check_visibility("idle", 0, 0, 1) is False

    def test_unknown_treated_as_idle(self):
        assert _zen_check_visibility("bogus", 0, 0, 0) is True
        assert _zen_check_visibility("bogus", 1, 0, 0) is False


# -- zone computation tests ----------------------------------------------------

class TestZoneComputation:
    def test_no_future_zones(self):
        zones = _zen_compute_zones(125, True, False, 0)
        names = [z[0] for z in zones]
        assert "past" in names
        assert "present" in names
        assert "near" not in names

    def test_queued_only(self):
        zones = _zen_compute_zones(125, True, True, 0)
        names = [z[0] for z in zones]
        assert "near" in names
        assert "medium" not in names

    def test_queued_plus_vision(self):
        zones = _zen_compute_zones(125, True, True, 2)
        names = [z[0] for z in zones]
        assert "past" in names
        assert "present" in names
        assert "near" in names
        assert "medium" in names
        assert "long" in names

    def test_77_percent_rule(self):
        zones = _zen_compute_zones(125, True, True, 2)
        past = [z for z in zones if z[0] == "past"][0]
        usable = 125 - 4
        expected_past = usable * 77 // 100
        assert past[1] == expected_past

    def test_no_items_no_past(self):
        zones = _zen_compute_zones(125, False, False, 0)
        names = [z[0] for z in zones]
        assert "past" not in names
        assert "present" in names


# -- dot positions tests -------------------------------------------------------

class TestDotPositions:
    def test_minimum_gap(self, zen_db):
        items = [
            (i, f"Item {i}", "yoke", "done", f"2025-06-{15 + i // 10:02d}")
            for i in range(1, 30)
        ]
        insert_zen_items(zen_db, items)
        with BoardDB(zen_db) as db:
            positions = _zen_item_positions(db, "yoke", "2025-06-01", 100)
        for i in range(1, len(positions)):
            assert positions[i] - positions[i - 1] >= 3

    def test_empty_returns_empty(self, zen_db):
        with BoardDB(zen_db) as db:
            positions = _zen_item_positions(db, "yoke", "2025-01-01", 100)
        assert positions == []


# -- VISION.md parsing tests ---------------------------------------------------

class TestVisionExtraction:
    def test_parses_sections(self, tmp_path):
        (tmp_path / ".yoke" / "strategy").mkdir(parents=True)
        vision = tmp_path / ".yoke" / "strategy" / "VISION.md"
        vision.write_text(textwrap.dedent("""\
            # Vision

            ### 1 Month
            - Autonomous testing
            - Better deploys

            ### 6 Months
            - Self healing infrastructure

            ### 1 Year
            - Full automation

            ### 5 Years
            - Sentient systems
        """))
        results = _zen_extract_vision(str(tmp_path))
        assert len(results) == 4
        keys = [r[0] for r in results]
        assert keys == ["1mo", "6mo", "1yr", "5yr"]
        assert results[0][1] == "autonomous t"

    def test_missing_vision_returns_empty(self, tmp_path):
        results = _zen_extract_vision(str(tmp_path))
        assert results == []

    def test_none_root_returns_empty(self):
        results = _zen_extract_vision(None)
        assert results == []


# -- query tests ---------------------------------------------------------------

class TestQueries:
    def test_query_projects(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "Done item", "yoke", "done", "2025-01-15"),
            (2, "Active item", "externalwebapp", "implementing", "2025-01-15"),
        ])
        with BoardDB(zen_db) as db:
            projects = _zen_query_projects(db)
        assert len(projects) == 1
        assert projects[0][0] == "yoke"

    def test_query_projects_honors_scope(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "Yoke done", "yoke", "done", "2025-01-15"),
            (2, "ExternalWebapp done", "externalwebapp", "done", "2025-01-15"),
        ])
        with BoardDB(zen_db) as db:
            projects = _zen_query_projects(db, "externalwebapp")
        assert projects == [("externalwebapp", "\U0001f9e9")]

    def test_queued_count(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "Idea", "yoke", "idea", "2025-01-15"),
            (2, "Planned", "yoke", "planned", "2025-01-15"),
            (3, "Done", "yoke", "done", "2025-01-15"),
        ])
        with BoardDB(zen_db) as db:
            count = _zen_queued_count(db, "yoke")
        assert count == 2

    def test_queued_count_excludes_frozen_terminal(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "Frozen idea", "yoke", "idea", "2025-01-15"),
            (2, "Frozen cancelled", "yoke", "cancelled", "2025-01-15"),
            (3, "Frozen stopped", "yoke", "stopped", "2025-01-15"),
            (4, "Frozen failed", "yoke", "failed", "2025-01-15"),
            (5, "Frozen done", "yoke", "done", "2025-01-15"),
        ])
        conn = connect_test_db(zen_db)
        conn.execute("UPDATE items SET frozen = 1")
        conn.commit()
        conn.close()
        with BoardDB(zen_db) as db:
            count = _zen_queued_count(db, "yoke")
        assert count == 1

    def test_compute_window(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "First", "yoke", "done", "2025-03-10 12:00:00"),
            (2, "Second", "yoke", "done", "2025-06-01 08:00:00"),
        ])
        with BoardDB(zen_db) as db:
            window = _zen_compute_window(db, "yoke")
        assert window == "2025-03-10"


# -- integration test ----------------------------------------------------------

class TestRenderZenWidget:
    def test_hidden_when_never(self, zen_db):
        cfg = BoardConfig(timeline_widget="never")
        with BoardDB(zen_db) as db:
            lines = render_zen_widget(db, cfg, "", 0, 0, 0)
        assert lines == []

    def test_hidden_when_idle_with_active(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "Done item", "yoke", "done", "2025-01-15"),
        ])
        cfg = BoardConfig(timeline_widget="idle")
        with BoardDB(zen_db) as db:
            lines = render_zen_widget(db, cfg, "", 1, 0, 0)
        assert lines == []

    def test_renders_with_done_items(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "Board renderer", "yoke", "done", "2025-01-15"),
            (2, "Config parser", "yoke", "done", "2025-02-01"),
            (3, "Deploy script", "yoke", "done", "2025-03-01"),
        ])
        cfg = BoardConfig(timeline_widget="always")
        with BoardDB(zen_db) as db:
            lines = render_zen_widget(db, cfg, "", 5, 3, 10)
        assert len(lines) >= 2
        combined = "".join(lines)
        assert "●" in combined or "━" in combined

    def test_render_honors_project_scope(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "Yoke done", "yoke", "done", "2025-01-15"),
            (2, "ExternalWebapp done", "externalwebapp", "done", "2025-01-15"),
        ])
        cfg = BoardConfig(timeline_widget="always")
        with BoardDB(zen_db) as db:
            lines = render_zen_widget(db, cfg, "externalwebapp", 0, 0, 0)
        combined = "\n".join(lines)
        assert "\U0001f9e9" in combined
        assert "\U0001f305" not in combined

    def test_empty_projects_returns_empty(self, zen_db):
        cfg = BoardConfig(timeline_widget="always")
        with BoardDB(zen_db) as db:
            lines = render_zen_widget(db, cfg, "", 0, 0, 0)
        assert lines == []
