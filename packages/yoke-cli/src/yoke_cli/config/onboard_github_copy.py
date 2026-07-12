"""Shared user-facing copy for GitHub App onboarding screens."""

from __future__ import annotations

MACHINE_GITHUB_TITLE = "Connect GitHub?"
MACHINE_GITHUB_SUBTITLE = (
    "Use the Yoke GitHub App to authorize this machine for local repo "
    "operations, or stay backlog-only."
)
MACHINE_GITHUB_REVIEW = "Connect this machine through the Yoke GitHub App"

PROJECT_GITHUB_PROMISE = (
    "Bind this project to a repository the Yoke GitHub App can access, or keep "
    "it backlog-only."
)

PROJECT_GITHUB_PROMPT_TITLE = "How should Yoke manage this project on GitHub?"
PROJECT_GITHUB_PROMPT_SUBTITLE = PROJECT_GITHUB_PROMISE

PROJECT_GITHUB_ACCESS_TITLE = "GitHub App repo binding is required."
PROJECT_GITHUB_ACCESS_SUBTITLE = (
    "Use a repository already available to the Yoke GitHub App, add repository "
    "access in GitHub, or keep this project backlog-only."
)

PROJECT_GITHUB_REVIEW = (
    "Bind this project to a GitHub App repository for Issues, PRs, CI, and Actions"
)

PROJECT_GITHUB_REUSE_LABEL = "Use connected repo"
PROJECT_GITHUB_REUSE_DESC = "bind this repo using existing App access"
PROJECT_GITHUB_STORE_LABEL = "Add repo access"
PROJECT_GITHUB_STORE_DESC = "open GitHub to change app access"
PROJECT_GITHUB_SKIP_LABEL = "Skip GitHub for this project"
PROJECT_GITHUB_SKIP_DESC = "backlog-only"

PROJECT_GITHUB_SETUP_HELP = (
    "Project GitHub automation now uses a Yoke GitHub App repo binding. "
    "Bind the selected repository, add App access, or keep this project backlog-only."
)


__all__ = [
    "MACHINE_GITHUB_TITLE",
    "MACHINE_GITHUB_SUBTITLE",
    "MACHINE_GITHUB_REVIEW",
    "PROJECT_GITHUB_PROMISE",
    "PROJECT_GITHUB_PROMPT_TITLE",
    "PROJECT_GITHUB_PROMPT_SUBTITLE",
    "PROJECT_GITHUB_ACCESS_TITLE",
    "PROJECT_GITHUB_ACCESS_SUBTITLE",
    "PROJECT_GITHUB_REVIEW",
    "PROJECT_GITHUB_REUSE_LABEL",
    "PROJECT_GITHUB_REUSE_DESC",
    "PROJECT_GITHUB_STORE_LABEL",
    "PROJECT_GITHUB_STORE_DESC",
    "PROJECT_GITHUB_SKIP_LABEL",
    "PROJECT_GITHUB_SKIP_DESC",
    "PROJECT_GITHUB_SETUP_HELP",
]
