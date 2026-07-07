"""Copy regressions for project git prerequisite guidance."""

from __future__ import annotations

from yoke_cli.config import project_git_prerequisite


def test_macos_missing_git_copy_matches_visible_actions() -> None:
    detail_lines = project_git_prerequisite.missing_git_detail_lines(
        platform_name="darwin",
        which=lambda _name: None,
    )

    assert project_git_prerequisite.required_summary() not in detail_lines
    assert "choose Try again" in detail_lines[0]
    assert "choose Check again" not in detail_lines[0]


def test_macos_install_handoff_copy_names_check_again() -> None:
    detail_lines = project_git_prerequisite.install_handoff_detail_lines(
        project_git_prerequisite.install_advice(
            platform_name="darwin",
            which=lambda _name: None,
        )
    )

    assert detail_lines[-1] == (
        "When it finishes, return here and choose Check again."
    )


__all__ = []
