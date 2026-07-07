"""Tests for yoke_contracts.board.config — BoardConfig parsing.

Covers:
- Default values
- Boolean, integer, string key parsing
- Rainbow sub-mode weight detection
- Inline comment stripping
- Missing/malformed config handling
- All config keys from the spec
"""

from __future__ import annotations

import json
import textwrap

import pytest

from yoke_contracts.board.config import BoardConfig, parse_config


class TestBoardConfigDefaults:
    """Default values match documented config semantics."""

    def test_dashboard_velocity_meter_off(self):
        assert BoardConfig().dashboard_velocity_meter is False

    def test_timeline_widget_idle(self):
        assert BoardConfig().timeline_widget == "idle"

    def test_timeline_scope_defaults_to_board_scope(self):
        assert BoardConfig().timeline_scope == ""

    def test_dashboard_sessions_scope_defaults_to_board_scope(self):
        assert BoardConfig().dashboard_sessions_scope == ""

    def test_art_frontier_since_zero(self):
        assert BoardConfig().art_frontier_since == 0

    def test_dashboard_meter_cap(self):
        assert BoardConfig().dashboard_meter_cap == 50

    def test_art_override_empty(self):
        assert BoardConfig().art_override == ""

    def test_art_weight_frontier(self):
        assert BoardConfig().art_weight_frontier == 50

    def test_rainbow_per_variant_mode_off(self):
        assert BoardConfig().rainbow_per_variant_mode is False

    def test_done_section_limit_default(self):
        assert BoardConfig().done_section_limit == 250


class TestParseConfig:
    """Parsing a config file into BoardConfig."""

    def test_basic_parsing(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            dashboard_velocity_meter=true
            timeline_widget=always
            timeline_scope=all
            dashboard_sessions_scope=all
            art_frontier_since=42
            done_section_limit=50
        """))
        cfg = parse_config(str(cfg_file))
        assert cfg.dashboard_velocity_meter is True
        assert cfg.timeline_widget == "always"
        assert cfg.timeline_scope == "all"
        assert cfg.dashboard_sessions_scope == "all"
        assert cfg.art_frontier_since == 42
        assert cfg.done_section_limit == 50

    def test_project_local_board_json(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".yoke").mkdir(parents=True)
        (repo / ".yoke" / "board.json").write_text(
            json.dumps({
                "dashboard_velocity_meter": True,
                "timeline_widget": "always",
                "art_frontier_since": 12,
            }),
            encoding="utf-8",
        )
        cfg = parse_config(None, repo_root=str(repo))
        assert cfg.art_frontier_since == 12
        assert cfg.dashboard_velocity_meter is True
        assert cfg.timeline_widget == "always"

    def test_wip_cap_is_not_board_config(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".yoke").mkdir(parents=True)
        (repo / ".yoke" / "board.json").write_text(
            json.dumps({"wip_cap": 30, "dashboard_weather": False}),
            encoding="utf-8",
        )

        cfg = parse_config(None, repo_root=str(repo))

        assert not hasattr(cfg, "wip_cap")
        assert cfg.dashboard_weather is False

    def test_inline_comments_stripped(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("art_frontier_since=7  # override\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.art_frontier_since == 7

    def test_comment_lines_skipped(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("# this is a comment\nart_frontier_since=3\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.art_frontier_since == 3

    def test_section_headers_skipped(self, tmp_path):
        """Lines without '=' (like section headers) are ignored."""
        cfg_file = tmp_path / "config"
        cfg_file.write_text("[section]\nart_frontier_since=4\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.art_frontier_since == 4

    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = parse_config(str(tmp_path / "nonexistent"))
        assert cfg.art_frontier_since == 0

    def test_bad_int_keeps_default(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("art_frontier_since=notanumber\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.art_frontier_since == 0  # default

    def test_bool_values(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            dashboard_velocity=false
            dashboard_weather=yes
            dashboard_types=1
            dashboard_age=0
            dashboard_badges=true
        """))
        cfg = parse_config(str(cfg_file))
        assert cfg.dashboard_velocity is False
        assert cfg.dashboard_weather is True
        assert cfg.dashboard_types is True
        assert cfg.dashboard_age is False
        assert cfg.dashboard_badges is True

    def test_art_override(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("art_override=emoji_3\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.art_override == "emoji_3"

    def test_art_weight_keys(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            art_weight_rainbow=10
            art_weight_emoji=30
            art_weight_ascii=15
            art_weight_mixed=25
            art_weight_frontier=60
        """))
        cfg = parse_config(str(cfg_file))
        assert cfg.art_weight_rainbow == 10
        assert cfg.art_weight_emoji == 30
        assert cfg.art_weight_ascii == 15
        assert cfg.art_weight_mixed == 25
        assert cfg.art_weight_frontier == 60

    def test_project_board_json_owns_art_weight_settings(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".yoke").mkdir(parents=True)
        (repo / ".yoke" / "board.json").write_text(
            json.dumps({
                "art_frontier_since": 42,
                "art_weight_frontier": 80,
                "art_weight_rainbow_halves": 5,
            }),
            encoding="utf-8",
        )
        cfg = parse_config(None, repo_root=str(repo))
        assert cfg.art_frontier_since == 42
        assert cfg.art_weight_frontier == 80
        assert cfg.rainbow_sub_weights["halves"] == 5

    def test_dashboard_meter_cap_parsing(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("dashboard_meter_cap=100\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.dashboard_meter_cap == 100

class TestRainbowSubWeights:
    """Rainbow sub-mode weight parsing and per-variant detection."""

    def test_named_sub_weights(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            art_weight_rainbow_random=10
            art_weight_rainbow_letters=20
        """))
        cfg = parse_config(str(cfg_file))
        assert cfg.art_weight_rainbow_random == 10
        assert cfg.art_weight_rainbow_letters == 20
        assert cfg.rainbow_per_variant_mode is True

    def test_per_variant_mode_activated(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("art_weight_rainbow_halves=5\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.rainbow_per_variant_mode is True
        assert cfg.rainbow_sub_weights["halves"] == 5

    def test_catch_all_sub_weight(self, tmp_path):
        """Unrecognized rainbow sub-modes go to rainbow_sub_weights dict."""
        cfg_file = tmp_path / "config"
        cfg_file.write_text("art_weight_rainbow_sparkle=15\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.rainbow_sub_weights.get("sparkle") == 15
        assert cfg.rainbow_per_variant_mode is True

    def test_no_sub_weights_means_no_per_variant(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("art_frontier_since=5\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.rainbow_per_variant_mode is False
        assert cfg.rainbow_sub_weights == {}

    def test_bad_sub_weight_skipped(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("art_weight_rainbow_bad=xyz\n")
        cfg = parse_config(str(cfg_file))
        assert cfg.rainbow_per_variant_mode is False
