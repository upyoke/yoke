"""Selection rows for clone-source Git prerequisite and retry screens."""

from __future__ import annotations

from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.onboard_wizard_widgets import SelectionRow


CLONE_REMOTE_ERROR_ROWS = [
    SelectionRow("edit", "Change URL", "enter a different repo"),
    SelectionRow("retry", "Try again", "rerun the check"),
    SelectionRow("back", "Back", "choose a different option"),
]

GIT_INSTALL_ERROR_ROWS = [
    SelectionRow("install", "Try install again", "run installer"),
    SelectionRow("retry", "Try again", "after fixing git"),
    SelectionRow("back", "Back", "choose a different project option"),
]


def missing_rows() -> list[SelectionRow]:
    advice = project_git_prerequisite.install_advice()
    rows: list[SelectionRow] = []
    if advice.run_steps:
        rows.append(SelectionRow(
            "install",
            project_git_prerequisite.install_action_label(advice),
            project_git_prerequisite.install_action_hint(advice),
        ))
    rows.extend((
        SelectionRow("retry", "Try again", "after installing git"),
        SelectionRow("back", "Back", "choose a different project option"),
    ))
    return rows


def install_error_rows() -> list[SelectionRow]:
    advice = project_git_prerequisite.install_advice()
    rows: list[SelectionRow] = []
    if advice.run_steps:
        rows.append(SelectionRow(
            "install",
            "Try install again",
            project_git_prerequisite.install_action_hint(advice),
        ))
    rows.extend(GIT_INSTALL_ERROR_ROWS[1:])
    return rows


def handoff_rows() -> list[SelectionRow]:
    return [
        SelectionRow("retry", "Check again", "after installer finishes"),
        SelectionRow("install", "Open installer again", "if it did not open"),
        SelectionRow("back", "Back", "choose a different project option"),
    ]


__all__ = [
    "CLONE_REMOTE_ERROR_ROWS",
    "handoff_rows",
    "install_error_rows",
    "missing_rows",
]
