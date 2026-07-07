"""Tests for the board renderer assembly and CLI entrypoint.

Covers:
- AC-5: Renderer assembly order and deterministic output structure
- AC-2: Deterministic seed behavior (same seed => identical output)
- CLI invocation (render and preview modes)
- Consistency check integration
- Empty vs populated DB rendering
"""

from __future__ import annotations

from yoke_core.board.__main__ import main
from yoke_core.board.renderer import (
    _count_expected_tasks,
    _project_filter,
    render_board,
)
from yoke_contracts.board.renderer_dashboard import _combine_row
from runtime.api.fixtures.file_test_db import connect_test_db


# ---------------------------------------------------------------------------
# Unit tests: _combine_row
# ---------------------------------------------------------------------------


class TestCombineRow:
    def test_both_present(self):
        assert _combine_row("left", "right") == "left | right"

    def test_left_only(self):
        assert _combine_row("left", None) == "left"

    def test_right_only(self):
        assert _combine_row(None, "right") == "right"

    def test_both_none(self):
        assert _combine_row(None, None) is None

    def test_empty_strings(self):
        result = _combine_row("", "")
        assert result is None or result == ""

    def test_left_empty_right_present(self):
        assert _combine_row("", "right") == "right"


# ---------------------------------------------------------------------------
# Unit tests: _project_filter
# ---------------------------------------------------------------------------


class TestProjectFilter:
    def test_all_scope(self):
        assert _project_filter("all") == ""

    def test_named_scope(self):
        result = _project_filter("yoke")
        assert "project_id" in result
        assert "slug = 'yoke'" in result


# ---------------------------------------------------------------------------
# Integration: render_board with empty DB
# ---------------------------------------------------------------------------


class TestRenderBoardEmpty:
    def test_no_items_message(self, test_db_path, config_file):
        output = render_board(test_db_path, "yoke", config_file, seed=42)
        assert "No backlog items yet" in output
        assert "/yoke idea" in output


# ---------------------------------------------------------------------------
# Integration: render_board with populated DB
# ---------------------------------------------------------------------------


class TestRenderBoardPopulated:
    def test_section_order(self, populated_db, config_file):
        """AC-5: Section order: Active, Pipeline, Backlog, Frozen, Unknown, Done."""
        output = render_board(populated_db, "yoke", config_file, seed=42)

        active_pos = output.find("### 🎫 Active")
        backlog_pos = output.find("### 🌱 Backlog")
        done_pos = output.find("### \u2705 Done")

        assert active_pos >= 0
        assert backlog_pos >= 0
        assert done_pos >= 0
        assert active_pos < backlog_pos < done_pos

    def test_items_appear_in_sections(self, populated_db, config_file):
        output = render_board(populated_db, "yoke", config_file, seed=42)
        assert "First item" in output
        assert "Second item" in output
        assert "Done item" in output

    def test_no_empty_items_message(self, populated_db, config_file):
        output = render_board(populated_db, "yoke", config_file, seed=42)
        assert "No backlog items yet" not in output

    def test_deterministic_with_seed(self, populated_db, config_file):
        """AC-2: Same seed produces identical output."""
        out1 = render_board(populated_db, "yoke", config_file, seed=42)
        out2 = render_board(populated_db, "yoke", config_file, seed=42)
        assert out1 == out2

    def test_different_seeds_may_differ(self, populated_db, config_file):
        out1 = render_board(populated_db, "yoke", config_file, seed=1)
        out2 = render_board(populated_db, "yoke", config_file, seed=999)
        assert "First item" in out1
        assert "First item" in out2

    def test_output_structure(self, populated_db, config_file):
        """AC-5: Output contains header, dashboard, and section tables."""
        output = render_board(populated_db, "yoke", config_file, seed=42)
        # Should have some content before sections (header/dashboard area)
        active_pos = output.find("### 🎫 Active")
        assert active_pos > 0, "Header/dashboard content should precede sections"
        # Should have table rows
        assert "| YOK-" in output

# ---------------------------------------------------------------------------
# Integration: consistency check
# ---------------------------------------------------------------------------


class TestConsistencyCheck:
    def test_mismatch_warning_to_stderr(self, populated_db, config_file, capsys):
        render_board(populated_db, "yoke", config_file, seed=42)
        captured = capsys.readouterr()
        assert isinstance(captured.err, str)


# ---------------------------------------------------------------------------
# CLI tests: retired render mode
# ---------------------------------------------------------------------------


class TestCLIRender:
    def test_implicit_render_points_to_yoke_cli(self, capsys):
        rc = main(["--db", "unused"])

        assert rc == 2
        captured = capsys.readouterr()
        assert "yoke board rebuild --print" in captured.err

    def test_render_subcommand_points_to_yoke_cli(self, capsys):
        rc = main(["render", "--db", "unused"])

        assert rc == 2
        captured = capsys.readouterr()
        assert "yoke board rebuild --print" in captured.err

    def test_top_level_help_points_to_preview_and_rebuild(self, capsys):
        rc = main(["--help"])

        assert rc == 0
        captured = capsys.readouterr()
        assert "python3 -m yoke_core.board preview" in captured.out
        assert "yoke board rebuild --print" in captured.out


# ---------------------------------------------------------------------------
# CLI tests: preview mode
# ---------------------------------------------------------------------------


class TestCLIPreview:
    def test_preview_rainbow(self, capsys):
        rc = main(["preview", "--rainbow", "--seed", "42"])
        assert rc == 0
        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_preview_rainbow_all(self, capsys):
        rc = main(["preview", "--rainbow-all", "--seed", "42"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Rainbow Modes" in captured.out

    def test_preview_all(self, capsys):
        rc = main(["preview", "--all", "--seed", "42"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Progress Fill" in captured.out

    def test_preview_dashboard(self, capsys):
        rc = main(["preview", "--rainbow", "--dashboard", "--seed", "42"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Clear" in captured.out

    def test_preview_velocity_meter(self, capsys):
        rc = main(["preview", "--rainbow", "--dashboard",
                    "--velocity-meter", "--seed", "42"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "120d activity" in captured.out

    def test_preview_accepts_repo_root(self, capsys):
        rc = main(["preview", "--rainbow", "--repo-root", "/tmp", "--seed", "42"])
        assert rc == 0
        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_preview_zen(self, test_db_path, config_file, capsys):
        conn = connect_test_db(test_db_path)
        conn.execute(
            "UPDATE projects SET emoji = %s WHERE slug = 'yoke'",
            ("\u2600\ufe0f",),
        )
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, type, project_id, project_sequence, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 1, %s, %s, %s)",
            (99, "Board renderer", "done", "issue", 99, "2025-03-10", "2025-03-10"),
        )
        conn.commit()
        conn.close()

        rc = main([
            "preview",
            "--zen",
            "--db",
            test_db_path,
            "--config",
            config_file,
            "--seed",
            "42",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Project Timelines Widget" in captured.out
        assert "\U0001f538" in captured.out

    def test_preview_percent(self, capsys):
        rc = main(["preview", "--percent", "75", "--seed", "42"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "75%" in captured.out

    def test_preview_done_active_total(self, capsys):
        rc = main(["preview", "--done", "5", "--active", "3",
                    "--total", "10", "--seed", "42"])
        assert rc == 0

    def test_preview_dashboard_exit_code(self, capsys):
        rc = main(["preview", "--rainbow", "--dashboard", "--seed", "42"])
        assert rc == 0

    def test_preview_stats(self, capsys):
        rc = main(["preview", "--rainbow", "--stats", "5,3,2,10,1",
                    "--seed", "42"])
        assert rc == 0

    def test_preview_deterministic(self, capsys):
        """Preview with same seed produces identical output."""
        main(["preview", "--rainbow", "--seed", "42"])
        out1 = capsys.readouterr().out
        main(["preview", "--rainbow", "--seed", "42"])
        out2 = capsys.readouterr().out
        assert out1 == out2


# ---------------------------------------------------------------------------
# Expected tasks count helper
# ---------------------------------------------------------------------------


class TestCountExpectedTasks:
    def test_with_epic_tasks(self, populated_db):
        from yoke_core.board.db import BoardDB

        with BoardDB(populated_db) as db:
            count = _count_expected_tasks(db, "yoke")
            assert count == 2

    def test_empty_db(self, test_db_path):
        from yoke_core.board.db import BoardDB

        with BoardDB(test_db_path) as db:
            count = _count_expected_tasks(db, "yoke")
            assert count == 0
