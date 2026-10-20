"""Shared workflow teaching scopes Yoke source checks to their own lanes."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


def test_source_lint_is_taught_only_under_yoke_repo_internals() -> None:
    text = _read(REPO / "AGENTS.md")
    assert text.index("# Yoke Repo Internals") < text.index("yoke dev ruff-changed")


def test_workflow_source_check_recipes_have_explicit_level_scope() -> None:
    for path in SKILLS.rglob("*.md"):
        text = _read(path)
        if any(
            command in text
            for command in ("yoke dev import-check", "yoke dev ruff-changed")
        ):
            assert "Only on a claimed Yoke source lane with changed Python" in text, (
                path
            )
