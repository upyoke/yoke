"""Tests for bootstrap.py — shared startup-read renderer.

Companion file ``test_bootstrap_skills.py`` covers skill discovery
(``list_skills`` / ``resolve_skill_path`` / the compatibility symlink
contract). This file holds the bootstrap-spec, file-resolution, and
render coverage.
"""

from __future__ import annotations

import json

import pytest

from runtime.harness.bootstrap import (
    doctrine_short,
    existing,
    load_spec,
    main,
    ordered_unique,
    read_file,
    render_compact,
    render_full,
    render_required_files,
    resolve_files,
)


@pytest.fixture
def spec_dir(tmp_path):
    """Create a minimal bootstrap spec and file tree."""
    spec = {
        "required_files": ["AGENTS.md", "docs/OVERVIEW.md"],
        "required_commands": [
            {"label": "Echo test", "command": "echo hello"}
        ],
        "recommended_files": [".yoke/BOARD.md"],
    }
    spec_path = tmp_path / "bootstrap-spec.json"
    spec_path.write_text(json.dumps(spec))

    (tmp_path / "AGENTS.md").write_text("# Claude rules")
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs" / "OVERVIEW.md").write_text("# Overview")
    (tmp_path / "docs" / "prompt-philosophy.md").write_text(
        'The short form is `**Be the giant.** We stand on inherited shoulders.`'
    )
    (tmp_path / ".yoke").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".yoke" / "BOARD.md").write_text("# Board")

    return tmp_path, spec_path, spec


class TestOrderedUnique:
    def test_deduplicates(self):
        assert ordered_unique(["a", "b", "a", "c"]) == ["a", "b", "c"]

    def test_skips_empty(self):
        assert ordered_unique(["", "a", "", "b"]) == ["a", "b"]

    def test_preserves_order(self):
        assert ordered_unique(["c", "b", "a"]) == ["c", "b", "a"]

    def test_empty_input(self):
        assert ordered_unique([]) == []


class TestLoadSpec:
    def test_loads_valid_spec(self, spec_dir):
        _, spec_path, expected = spec_dir
        result = load_spec(spec_path)
        assert result["required_files"] == expected["required_files"]


class TestReadFile:
    def test_reads_existing(self, spec_dir):
        root, _, _ = spec_dir
        content = read_file(root, "AGENTS.md")
        assert content == "# Claude rules"

    def test_returns_none_for_missing(self, spec_dir):
        root, _, _ = spec_dir
        assert read_file(root, "nonexistent.md") is None


class TestDoctrineShort:
    def test_extracts_doctrine(self, spec_dir):
        root, _, _ = spec_dir
        result = doctrine_short(root)
        assert "Be the giant" in result

    def test_returns_empty_when_missing(self, tmp_path):
        assert doctrine_short(tmp_path) == ""


class TestExisting:
    def test_filters_to_existing(self, spec_dir):
        root, _, _ = spec_dir
        result = existing(root, ["AGENTS.md", "nonexistent.md", "docs/OVERVIEW.md"])
        assert result == ["AGENTS.md", "docs/OVERVIEW.md"]


class TestResolveFiles:
    def test_merges_extras_and_spec(self, spec_dir):
        _, _, spec = spec_dir
        required, recommended = resolve_files(spec, ["EXTRA.md"])
        assert required[0] == "EXTRA.md"
        assert "AGENTS.md" in required
        assert ".yoke/BOARD.md" in recommended


class TestRenderRequiredFiles:
    def test_one_per_line(self, spec_dir):
        _, _, spec = spec_dir
        result = render_required_files(spec, ["EXTRA.md"])
        lines = result.strip().split("\n")
        assert lines[0] == "EXTRA.md"
        assert "AGENTS.md" in lines


class TestRenderCompact:
    def test_includes_doctrine_and_files(self, spec_dir):
        root, _, spec = spec_dir
        result = render_compact(root, spec)
        assert "Prompt Doctrine:" in result
        assert "Be the giant" in result
        assert "Critical Runtime Invariants:" in result
        assert "worktree paths db" in result
        assert "- AGENTS.md" in result


class TestRenderFull:
    def test_includes_file_contents_and_commands(self, spec_dir):
        root, _, spec = spec_dir
        result = render_full(root, spec)
        assert "=== Critical Runtime Invariants ===" in result
        assert "worktree paths db" in result
        assert "=== AGENTS.md ===" in result
        assert "# Claude rules" in result
        assert "=== Echo test ===" in result
        assert "hello" in result

    def test_includes_recommended(self, spec_dir):
        root, _, spec = spec_dir
        result = render_full(root, spec)
        assert "=== .yoke/BOARD.md ===" in result


class TestCLI:
    def test_required_files(self, spec_dir, capsys):
        root, spec_path, _ = spec_dir
        main(["required-files", "--spec", str(spec_path), "--root", str(root)])
        out = capsys.readouterr().out
        assert "AGENTS.md" in out

    def test_doctrine_short(self, spec_dir, capsys):
        root, spec_path, _ = spec_dir
        main(["doctrine-short", "--spec", str(spec_path), "--root", str(root)])
        out = capsys.readouterr().out
        assert "Be the giant" in out

    def test_render_compact(self, spec_dir, capsys):
        root, spec_path, _ = spec_dir
        main(["render-compact", "--spec", str(spec_path), "--root", str(root)])
        out = capsys.readouterr().out
        assert "Critical Runtime Invariants:" in out
        assert "Read before editing:" in out

    def test_unknown_mode(self, spec_dir):
        _, spec_path, _ = spec_dir
        with pytest.raises(SystemExit, match="1"):
            main(["bogus", "--spec", str(spec_path)])
