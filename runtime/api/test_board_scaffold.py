"""Tests for the board package scaffold: DB layer + config parser.

Covers:
- BoardDB context manager, query, scalar, query_quiet
- BoardConfig defaults and parse_config from a key=value file
- Rainbow per-variant mode detection
- Inline comment stripping, missing file handling
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts.board.config import BoardConfig, parse_config
from yoke_core.board.db import BoardDB
from runtime.api.fixtures.file_test_db import init_test_db


@pytest.fixture
def board_db_path(tmp_path):
    with init_test_db(tmp_path, apply_schema=lambda: None) as path:
        yield path


# ---------------------------------------------------------------------------
# BoardDB tests
# ---------------------------------------------------------------------------


class TestBoardDB:
    """Tests for the BoardDB wrapper."""

    def test_query_returns_rows(self, board_db_path):
        db_path = board_db_path
        with BoardDB(db_path) as db:
            db._conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
            db._conn.execute("INSERT INTO t VALUES (1, 'alice')")
            db._conn.execute("INSERT INTO t VALUES (2, 'bob')")
            rows = db.query("SELECT id, name FROM t ORDER BY id")
            assert rows == [(1, "alice"), (2, "bob")]

    def test_query_with_params(self, board_db_path):
        db_path = board_db_path
        with BoardDB(db_path) as db:
            db._conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
            db._conn.execute("INSERT INTO t VALUES (1, 'alice')")
            db._conn.execute("INSERT INTO t VALUES (2, 'bob')")
            rows = db.query("SELECT name FROM t WHERE id = %s", (2,))
            assert rows == [("bob",)]

    def test_scalar_returns_first_column(self, board_db_path):
        db_path = board_db_path
        with BoardDB(db_path) as db:
            result = db.scalar("SELECT 42")
            assert result == 42

    def test_scalar_returns_none_for_empty(self, board_db_path):
        db_path = board_db_path
        with BoardDB(db_path) as db:
            db._conn.execute("CREATE TABLE t (id INTEGER)")
            result = db.scalar("SELECT id FROM t")
            assert result is None

    def test_query_quiet_returns_empty_on_missing_table(self, board_db_path):
        db_path = board_db_path
        with BoardDB(db_path) as db:
            rows = db.query_quiet("SELECT * FROM nonexistent_table")
            assert rows == []

    def test_query_quiet_returns_empty_on_missing_column(self, board_db_path):
        db_path = board_db_path
        with BoardDB(db_path) as db:
            db._conn.execute("CREATE TABLE t (id INTEGER)")
            rows = db.query_quiet("SELECT nonexistent FROM t")
            assert rows == []

    def test_close_is_idempotent(self, board_db_path):
        db_path = board_db_path
        db = BoardDB(db_path)
        db.close()
        # Second close should not raise
        db.close()


# ---------------------------------------------------------------------------
# BoardConfig tests
# ---------------------------------------------------------------------------


class TestBoardConfig:
    """Tests for the BoardConfig dataclass and parse_config."""

    def test_defaults(self):
        cfg = BoardConfig()
        assert cfg.dashboard_velocity is True
        assert cfg.dashboard_weather is True
        assert cfg.dashboard_velocity_meter is False
        assert cfg.timeline_widget == "idle"
        assert cfg.art_frontier_since == 0
        assert cfg.dashboard_meter_cap == 50
        assert cfg.art_weight_rainbow == 20
        assert cfg.art_weight_frontier == 50
        assert cfg.art_override == ""
        assert cfg.rainbow_per_variant_mode is False

    def test_parse_basic_config(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            "dashboard_velocity_meter=true\n"
            "timeline_widget=always\n"
            "art_frontier_since=100\n"
            "art_weight_frontier=80\n"
        )
        cfg = parse_config(str(config_file))
        assert cfg.dashboard_velocity_meter is True
        assert cfg.timeline_widget == "always"
        assert cfg.art_frontier_since == 100
        assert cfg.art_weight_frontier == 80

    def test_parse_skips_comments_and_blanks(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            "# This is a comment\n"
            "\n"
            "  # Indented comment\n"
            "art_frontier_since=15\n"
            "\n"
        )
        cfg = parse_config(str(config_file))
        assert cfg.art_frontier_since == 15

    def test_parse_skips_section_headers(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            "## Master Map\n"
            "art_frontier_since=20\n"
            "Some Section Header Without Equals\n"
        )
        cfg = parse_config(str(config_file))
        assert cfg.art_frontier_since == 20

    def test_parse_strips_inline_comments(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text("art_frontier_since=25  # default is 0\n")
        cfg = parse_config(str(config_file))
        assert cfg.art_frontier_since == 25

    def test_parse_bool_values(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            "dashboard_weather=false\n"
            "dashboard_velocity_meter=true\n"
            "dashboard_types=1\n"
            "dashboard_age=yes\n"
            "dashboard_badges=no\n"
        )
        cfg = parse_config(str(config_file))
        assert cfg.dashboard_weather is False
        assert cfg.dashboard_velocity_meter is True
        assert cfg.dashboard_types is True
        assert cfg.dashboard_age is True
        assert cfg.dashboard_badges is False

    def test_parse_missing_file_returns_defaults(self, tmp_path):
        cfg = parse_config(str(tmp_path / "nonexistent"))
        assert cfg.art_frontier_since == 0

    def test_parse_bad_int_keeps_default(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text("art_frontier_since=not_a_number\n")
        cfg = parse_config(str(config_file))
        assert cfg.art_frontier_since == 0  # default

    def test_rainbow_sub_weights(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text(
            "art_weight_rainbow_random=8\n"
            "art_weight_rainbow_letters=8\n"
        )
        cfg = parse_config(str(config_file))
        assert cfg.art_weight_rainbow_random == 8
        assert cfg.art_weight_rainbow_letters == 8
        assert cfg.rainbow_per_variant_mode is True
        assert cfg.rainbow_sub_weights == {"random": 8, "letters": 8}

    def test_rainbow_sub_weights_empty_when_none_set(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text("art_frontier_since=5\n")
        cfg = parse_config(str(config_file))
        assert cfg.rainbow_per_variant_mode is False
        assert cfg.rainbow_sub_weights == {}

    def test_unknown_rainbow_sub_mode(self, tmp_path):
        """Future rainbow sub-modes go into the catch-all dict."""
        config_file = tmp_path / "config"
        config_file.write_text("art_weight_rainbow_sparkle=12\n")
        cfg = parse_config(str(config_file))
        assert cfg.rainbow_sub_weights == {"sparkle": 12}
        assert cfg.rainbow_per_variant_mode is True

    def test_art_override(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text("art_override=rainbow_gradient\n")
        cfg = parse_config(str(config_file))
        assert cfg.art_override == "rainbow_gradient"

    def test_dashboard_meter_cap(self, tmp_path):
        config_file = tmp_path / "config"
        config_file.write_text("dashboard_meter_cap=100\n")
        cfg = parse_config(str(config_file))
        assert cfg.dashboard_meter_cap == 100

    def test_parse_machine_and_project_config(self, tmp_path, monkeypatch):
        """Parse machine config plus project-local board art settings."""
        machine_cfg = tmp_path / "config.json"
        machine_cfg.write_text(
            json.dumps(
                {"schema_version": 1, "settings": {}}
            ),
            encoding="utf-8",
        )
        repo_root = tmp_path / "repo"
        board_config = repo_root / ".yoke" / "board.json"
        board_config.parent.mkdir(parents=True)
        board_config.write_text(
            json.dumps({
                "art_frontier_since": 3,
                "dashboard_meter_cap": 100,
            }),
            encoding="utf-8",
        )
        monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(machine_cfg))

        cfg = parse_config(None, repo_root=str(repo_root))

        assert cfg.art_frontier_since == 3
        assert cfg.dashboard_meter_cap == 100


# ---------------------------------------------------------------------------
# Package import tests
# ---------------------------------------------------------------------------


class TestPackageImports:
    """Verify the board package re-exports work."""

    def test_import_board_db(self):
        from yoke_core.board import BoardDB  # noqa: F811

        assert BoardDB is not None

    def test_import_board_config(self):
        from yoke_core.board import BoardConfig, parse_config  # noqa: F811

        assert BoardConfig is not None
        assert parse_config is not None

    def test_import_domain_reexports(self):
        from yoke_core.board import (  # noqa: F811
            BoardProjection,
            BoardStats,
            ItemForBoard,
            project_board,
            status_to_board_bucket,
        )

        assert BoardProjection is not None
        assert BoardStats is not None
        assert status_to_board_bucket is not None
        assert project_board is not None
        assert ItemForBoard is not None
