"""Selection rows for clone-source Git prerequisite and retry screens."""

from __future__ import annotations

from yoke_cli.config import onboard_github_copy
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.onboard_wizard_widgets import SelectionRow

UNREACHABLE_RECOVERY_LINES = [onboard_github_copy.CLONE_CONNECT_RECOVERY]

CLONE_REMOTE_ERROR_ROWS = [
    SelectionRow("edit", "Change URL", "enter a different repo"),
    SelectionRow("retry", "Try again", "rerun the check"),
    SelectionRow("back", "Back", "choose a different option"),
]

PRIVATE_REMOTE_ERROR_ROWS = [
    SelectionRow(
        "repositories", "Refresh private repositories", "reload App access",
    ),
    SelectionRow("retry", "Try again", "rerun the check"),
    SelectionRow("back", "Back", "choose public or private"),
]

GIT_INSTALL_ERROR_ROWS = [
    SelectionRow("install", "Try install again", "run installer"),
    SelectionRow("retry", "Try again", "after fixing git"),
    SelectionRow("back", "Back", "choose a different project option"),
]


def unreachable_source_reason(
    *,
    configured_origin: bool,
    used_connected_github: bool,
    credential_error: str | None,
    denied_access: bool,
) -> str:
    """Name why a source repo stayed unreadable, and what would make it readable."""

    if credential_error:
        return (
            "Yoke couldn't refresh the GitHub access you connected, and the "
            f"repo isn't readable without it: {credential_error} Reconnect "
            "GitHub, then try again."
        )
    if used_connected_github:
        return (
            "Yoke couldn't read that repo with the GitHub access you "
            "connected. Check the URL, and confirm the Yoke GitHub App has "
            "access to that repository."
        )
    if not configured_origin:
        return (
            "Yoke couldn't reach that repo. GitHub App authorization is never "
            "sent outside the configured GitHub origin, so an external HTTPS "
            "repo has to be readable without credentials. Check the URL and "
            "network connection."
        )
    del denied_access
    return onboard_github_copy.CLONE_MISSING_AUTHORIZATION


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
    "PRIVATE_REMOTE_ERROR_ROWS",
    "UNREACHABLE_RECOVERY_LINES",
    "handoff_rows",
    "install_error_rows",
    "missing_rows",
    "unreachable_source_reason",
]
