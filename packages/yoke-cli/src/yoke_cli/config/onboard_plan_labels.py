"""Friendly labels for ``yoke onboard`` write-plan steps."""

from __future__ import annotations

from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_project
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_JUST_CLONE,
    CLONE_OUTCOME_MAKE_IT_MINE,
)

_RUNTIME_DIR_LABELS = {
    "temp_root": "scratch",
    "cache_dir": "cache",
}
_PROJECT_MODE_LABELS = {
    onboard_project.PROJECT_MODE_CREATE_REPO: "a new project",
    onboard_project.PROJECT_MODE_CLONE_REMOTE: "a clone of a GitHub repo",
    onboard_project.PROJECT_MODE_IMPORT_REMOTE: "an imported GitHub repo",
    onboard_project.PROJECT_MODE_LOCAL_CHECKOUT: "an existing folder",
    onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN: "the Yoke source checkout",
}
_CLONE_OUTCOME_LABELS = {
    CLONE_OUTCOME_MAKE_IT_MINE: " and re-home it onto a new repo we'll create",
    CLONE_OUTCOME_FORK: " as a fork you can PR back",
    CLONE_OUTCOME_JUST_CLONE: "",
}


def friendly_line(action: str, target: str, project_name: str = "") -> str:
    """Render one plan step as a plain "what (and where/why)" line."""
    if action == "create-or-validate-dir":
        return f"Create your Yoke home folder at {target}"
    if action == "set-active-env":
        return f'Make "{target}" your active environment'
    if action == "set-https-api-url":
        return f"Connect to {target}"
    if action == "local-universe-init":
        return (
            "Create (or verify) this machine's local Yoke universe under "
            "~/.yoke"
        )
    if action == "store-token-reference":
        return "Save your API token (owner-only)"
    if action == "machine-github-connection":
        return (onboard_github_copy.MACHINE_TOKEN_REVIEW if target == "connect"
                else "Skip connecting GitHub for now")
    if action == "create-runtime-dir":
        return f"Set up the {_RUNTIME_DIR_LABELS.get(target, target)} directory"
    if action == "project-source-choice":
        mode, _, outcome = target.partition(":")
        if mode == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN:
            # The core DB records the Yoke PROJECT, not this checkout's path —
            # the path is registered in ~/.yoke/config.json (see the separate
            # project-checkout-register line).
            return "Register the Yoke project in the Yoke core database"
        base = _PROJECT_MODE_LABELS.get(mode, mode)
        who = project_name or "the project"
        return (
            f"Record {who} in the Yoke core database as "
            f"{base}{_CLONE_OUTCOME_LABELS.get(outcome, '')}"
        )
    if action == "project-create-checkout":
        return f"Create the project at {target}"
    if action == "project-clone-remote":
        return f"Clone the project into {target}"
    if action == "project-import-remote":
        return f"Import the project at {target}"
    if action in ("project-onboard-local-checkout", "project-onboard"):
        return f"Set up the project at {target}"
    if action == "project-checkout-register":
        return f"Register this checkout in ~/.yoke/config.json: {target}"
    if action == "project-rehome-push":
        return "Re-home onto the new repo and push"
    if action == "project-fork-remotes":
        return "Point origin at your fork and track the source as upstream"
    if action == "project-install-scaffold":
        return "Install the Yoke project scaffold (.yoke/)"
    if action == "project-refresh-scaffold":
        return "Refresh the Yoke project scaffold (.yoke/)"
    if action == "project-write-board-art":
        return "Write your board art and initial BOARD.md"
    if action == "project-source-dev-admin":
        return f"Set up the Yoke source checkout at {target}"
    if action == "project-github-auth-choice":
        if target == "existing-project":
            return (
                "Use GitHub settings already stored in the Yoke core database "
                "for this project"
            )
        if target == "keep-existing-remote":
            return "Keep this folder's existing GitHub remote"
        if target == "source-dev":
            return "Use Yoke's GitHub \"origin\" remote from the clone"
        return ("Don't set up Yoke with access to a GitHub remote"
                if target in ("skip", "")
                else onboard_github_copy.PROJECT_TOKEN_REVIEW)
    humanized = action.replace("-", " ").replace("_", " ").strip().capitalize()
    return f"{humanized}: {target}" if target else humanized


__all__ = ["friendly_line"]
