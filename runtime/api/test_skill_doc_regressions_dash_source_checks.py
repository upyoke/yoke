"""Shared workflow teaching scopes Yoke source checks to their own lanes."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


def test_dash_scopes_source_checks_before_teaching_commands() -> None:
    text = _read(SKILLS / "dash" / "implement.md")
    scope = "Only on a claimed Yoke source lane with changed Python"
    for command in ("yoke dev import-check", "yoke dev ruff-changed"):
        assert text.index(scope) < text.index(command)
    assert "skip it when there are none" in text
    assert (
        "For other projects, run their own declared lint, format, and import smoke"
        in text
    )
    assert "A change with no Python" in text


def test_workflow_source_check_recipes_have_explicit_lane_scope() -> None:
    for path in SKILLS.rglob("*.md"):
        text = _read(path)
        if any(
            command in text
            for command in ("yoke dev import-check", "yoke dev ruff-changed")
        ):
            assert "Only on a claimed Yoke source lane with changed Python" in text, (
                path
            )
