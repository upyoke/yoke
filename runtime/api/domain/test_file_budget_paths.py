"""Tests for the shared File Budget path extractor."""

from __future__ import annotations

import pytest

from yoke_core.domain.file_budget_paths import (
    extract_file_budget_paths,
    extract_file_budget_paths_set,
    is_path_token,
)


class TestIsPathToken:
    def test_extensionless_with_slash_accepted(self):
        assert is_path_token(".yoke/lint-config") is True

    def test_nested_extensionless_accepted(self):
        assert is_path_token("runtime/api/data/seed") is True

    def test_extensioned_py_accepted(self):
        assert is_path_token("runtime/api/domain/foo.py") is True

    def test_directory_token_rejected(self):
        assert is_path_token("runtime/api/") is False

    def test_token_without_slash_rejected(self):
        assert is_path_token("release_item_claim") is False

    def test_shell_fragment_rejected(self):
        assert is_path_token(">/dev/null") is False
        assert is_path_token("2>&1") is False

    def test_top_level_allcaps_markdown_accepted(self):
        assert is_path_token("AGENTS.md") is True
        assert is_path_token("CLAUDE.md") is True

    def test_top_level_dotfile_accepted(self):
        assert is_path_token(".gitignore") is True
        assert is_path_token(".prettierrc") is True

    def test_top_level_build_config_accepted(self):
        assert is_path_token("pyproject.toml") is True
        assert is_path_token("package.json") is True

    def test_lowercase_top_level_markdown_rejected(self):
        assert is_path_token("readme.md") is False

    def test_empty_rejected(self):
        assert is_path_token("") is False

    def test_dotted_identifier_function_id_rejected(self):
        assert is_path_token("items.section.upsert") is False
        assert is_path_token("items.structured_field.replace") is False
        assert is_path_token("claims.path.register") is False
        assert is_path_token("db_claim.amend") is False

    def test_dotted_identifier_module_path_rejected(self):
        assert is_path_token("yoke_core.domain.foo") is False


class TestFunctionIdsInFileBudgetReproductionShape:
    """Two consecutive rewrites of a prior ticket were blocked because the
    operator listed function ids in ``## File Budget`` backticks. The
    parser must surface only real paths and silently ignore dotted-
    identifier tokens, even when they sit alongside real paths.
    """

    def test_function_ids_only_extract_to_empty(self):
        spec = (
            "## File Budget\n\n"
            "- `items.section.upsert` — operator surface.\n"
            "- `items.structured_field.replace` — operator surface.\n"
            "- `claims.path.register` — operator surface.\n"
            "- `db_claim.amend` — operator surface.\n"
        )
        assert extract_file_budget_paths(spec) == []

    def test_mixed_paths_and_function_ids_extract_paths_only(self):
        spec = (
            "## File Budget\n\n"
            "- `runtime/api/domain/foo.py` — real path.\n"
            "- `items.section.upsert` — function id, must not extract.\n"
            "- `.gitignore` — real top-level dotfile.\n"
            "- `db_claim.amend` — function id, must not extract.\n"
            "- `AGENTS.md` — real top-level ALLCAPS markdown.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "runtime/api/domain/foo.py",
            ".gitignore",
            "AGENTS.md",
        ]


class TestExtractFileBudgetPaths:
    def test_project_local_extensionless_picked_up(self):
        spec = (
            "## File Budget\n\n"
            "- `.yoke/lint-config` — project lint policy.\n"
        )
        assert extract_file_budget_paths(spec) == [".yoke/lint-config"]

    def test_extensioned_paths_still_extract(self):
        spec = (
            "## File Budget\n\n"
            "- `runtime/api/domain/foo.py` — helper.\n"
            "- `docs/lifecycle.md` — operator note.\n"
            "- `runtime/harness/claude/settings.json` — hook wire-up.\n"
            "- `.yoke/strategy/WISPS.md` — flip state.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "runtime/api/domain/foo.py",
            "docs/lifecycle.md",
            "runtime/harness/claude/settings.json",
            ".yoke/strategy/WISPS.md",
        ]

    def test_top_level_allcaps_markdown_extracted(self):
        spec = (
            "## File Budget\n\n"
            "- `AGENTS.md` — promote rule.\n"
            "- `CLAUDE.md` — companion update.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "AGENTS.md",
            "CLAUDE.md",
        ]

    def test_top_level_dotfile_extracted(self):
        spec = (
            "## File Budget\n\n"
            "- `.gitignore` — remove stale ignore rule.\n"
            "- `runtime/api/domain/foo.py` — implementation anchor.\n"
        )
        assert extract_file_budget_paths(spec) == [
            ".gitignore",
            "runtime/api/domain/foo.py",
        ]

    def test_top_level_build_config_extracted(self):
        spec = (
            "## File Budget\n\n"
            "- `pyproject.toml` — package metadata.\n"
            "- `runtime/api/domain/foo.py` — implementation anchor.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "pyproject.toml",
            "runtime/api/domain/foo.py",
        ]

    def test_directory_token_filtered(self):
        spec = (
            "## File Budget\n\n"
            "- `runtime/api/domain/` — directory only, must not extract.\n"
            "- `runtime/api/domain/anchor.py` — anchor entry.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "runtime/api/domain/anchor.py",
        ]

    def test_inline_symbol_without_slash_filtered(self):
        spec = (
            "## File Budget\n\n"
            "- `runtime/api/domain/sessions.py` calls "
            "`release_item_claim` — bare symbol must not extract.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "runtime/api/domain/sessions.py",
        ]

    def test_shell_fragment_filtered(self):
        spec = (
            "## File Budget\n\n"
            "- `runtime/api/domain/foo.py` — replaces "
            "`>/dev/null 2>&1 || true`.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "runtime/api/domain/foo.py",
        ]

    def test_dedupes_duplicates(self):
        spec = (
            "## File Budget\n\n"
            "- `.yoke/lint-config` — first mention.\n"
            "- `.yoke/lint-config` — second mention.\n"
        )
        assert extract_file_budget_paths(spec) == [".yoke/lint-config"]

    def test_unbackticked_path_in_prose_ignored(self):
        spec = (
            "## File Budget\n\n"
            "- `runtime/api/domain/foo.py` is the real entry; the "
            "literal .yoke/lint-config in prose must not extract.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "runtime/api/domain/foo.py",
        ]

    def test_section_terminates_at_next_level2_heading(self):
        spec = (
            "## File Budget\n\n"
            "- `runtime/api/domain/foo.py` — in budget.\n\n"
            "## Acceptance Criteria\n\n"
            "- `runtime/api/domain/never_in_budget.py` — outside.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "runtime/api/domain/foo.py",
        ]

    def test_section_continues_through_level3_subheadings(self):
        spec = (
            "## File Budget\n\n"
            "### Current pressure\n\n"
            "- `runtime/api/domain/alpha.py` — first sub.\n\n"
            "### Sibling-module plan\n\n"
            "- `runtime/api/domain/beta.py` — second sub.\n\n"
            "## Acceptance Criteria\n\n"
            "- `runtime/api/domain/never.py` — outside.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "runtime/api/domain/alpha.py",
            "runtime/api/domain/beta.py",
        ]

    def test_multiple_paths_per_line(self):
        spec = (
            "## File Budget\n\n"
            "- `runtime/api/test_foo.py` and `runtime/api/test_bar.py` — both.\n"
        )
        assert extract_file_budget_paths(spec) == [
            "runtime/api/test_foo.py",
            "runtime/api/test_bar.py",
        ]

    def test_no_section_returns_empty(self):
        assert extract_file_budget_paths("# Title\n\nbody only") == []

    def test_empty_string_returns_empty(self):
        assert extract_file_budget_paths("") == []

    def test_set_helper_returns_same_paths_as_set(self):
        spec = (
            "## File Budget\n\n"
            "- `.yoke/lint-config` — first.\n"
            "- `runtime/api/domain/foo.py` — second.\n"
        )
        assert extract_file_budget_paths_set(spec) == {
            ".yoke/lint-config",
            "runtime/api/domain/foo.py",
        }


class TestExtensionlessPathReproductionShape:
    """Produced the failure: an extensionless path was claimed but readiness
    reported `CLAIM_NOT_IN_FILE_BUDGET` because the extractor ignored
    extensionless paths. The shared parser must surface `.yoke/lint-config`
    so claim/budget consistency can succeed."""

    def test_project_lint_config_visible_to_consistency_check(self):
        spec = (
            "## File Budget\n\n"
            "- `.yoke/lint-config` — lint policy being widened.\n"
            "- `runtime/api/domain/foo.py` — call site.\n"
        )
        paths = extract_file_budget_paths_set(spec)
        # Both pieces of the shape must appear together.
        assert ".yoke/lint-config" in paths
        assert "runtime/api/domain/foo.py" in paths


class TestYOK1710ReproductionShape:
    """YOK-1710 lists `.gitignore` in the File Budget and path claim.

    Top-level dotfiles must be visible to claim/budget consistency so
    the readiness gate does not narrow away real deletion scope.
    """

    def test_gitignore_visible_to_consistency_check(self):
        spec = (
            "## File Budget\n\n"
            "- `.gitignore` — remove stale generated-view ignore rule.\n"
            "- `runtime/api/domain/retired_command.py` — remove retired command.\n"
        )
        paths = extract_file_budget_paths_set(spec)
        assert ".gitignore" in paths
        assert "runtime/api/domain/retired_command.py" in paths


class TestYOK1902ReproductionShape:
    """YOK-1902 claims root `pyproject.toml` in the File Budget.

    Lowercase dotted function ids must stay filtered, but known root
    build/config files need to be visible to claim/budget consistency.
    """

    def test_pyproject_visible_to_consistency_check(self):
        spec = (
            "## File Budget\n\n"
            "- `pyproject.toml` — root package metadata.\n"
            "- `items.section.upsert` — function id, must not extract.\n"
            "- `runtime/api/domain/file_budget_paths.py` — parser fix.\n"
        )
        paths = extract_file_budget_paths_set(spec)
        assert "pyproject.toml" in paths
        assert "runtime/api/domain/file_budget_paths.py" in paths
        assert "items.section.upsert" not in paths


@pytest.mark.parametrize(
    "candidate, expected",
    [
        (".yoke/lint-config", True),
        ("runtime/api/domain/foo.py", True),
        ("AGENTS.md", True),
        (".gitignore", True),
        ("pyproject.toml", True),
        ("package.json", True),
        (".", False),
        ("..", False),
        ("runtime/api/", False),
        ("release_item_claim", False),
        (">/dev/null", False),
        ("items.section.upsert", False),
        ("items.structured_field.replace", False),
        ("claims.path.register", False),
        ("db_claim.amend", False),
    ],
)
def test_is_path_token_table(candidate, expected):
    """Parametrized table covering the canonical accept/reject set."""
    assert is_path_token(candidate) is expected
