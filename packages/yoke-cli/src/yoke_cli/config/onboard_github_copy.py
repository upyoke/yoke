"""Shared user-facing copy for GitHub App onboarding screens."""

from __future__ import annotations

MACHINE_TOKEN_TITLE = "Connect GitHub?"
MACHINE_TOKEN_SUBTITLE = (
    "Use the Yoke GitHub App to authorize this machine for local repo "
    "operations, or stay backlog-only."
)
MACHINE_TOKEN_REVIEW = "Connect this machine through the Yoke GitHub App"

PROJECT_TOKEN_PROMISE = (
    "Bind this project to a repository the Yoke GitHub App can access, or keep "
    "it backlog-only."
)

PROJECT_GITHUB_PROMPT_TITLE = "How should Yoke manage this project on GitHub?"
PROJECT_GITHUB_PROMPT_SUBTITLE = PROJECT_TOKEN_PROMISE

PROJECT_TOKEN_PASTE_TITLE = "GitHub App repo binding is required."
PROJECT_TOKEN_PASTE_SUBTITLE = (
    "Use a repository already available to the Yoke GitHub App, add repository "
    "access in GitHub, or keep this project backlog-only."
)

PROJECT_TOKEN_REVIEW = (
    "Bind this project to a GitHub App repository for Issues, PRs, CI, and Actions"
)

PROJECT_GITHUB_REUSE_LABEL = "Use connected repo"
PROJECT_GITHUB_REUSE_DESC = "select from GitHub App repository access"
PROJECT_GITHUB_STORE_LABEL = "Add repo access"
PROJECT_GITHUB_STORE_DESC = "open GitHub to change app access"
PROJECT_GITHUB_SKIP_LABEL = "Skip GitHub for this project"
PROJECT_GITHUB_SKIP_DESC = "backlog-only"

PROJECT_TOKEN_ADOPTION_HELP = (
    "Project GitHub automation now uses a Yoke GitHub App repo binding. "
    "Use skip/backlog-only until repo binding is available in this setup flow."
)


__all__ = [
    "MACHINE_TOKEN_TITLE",
    "MACHINE_TOKEN_SUBTITLE",
    "MACHINE_TOKEN_REVIEW",
    "PROJECT_TOKEN_PROMISE",
    "PROJECT_GITHUB_PROMPT_TITLE",
    "PROJECT_GITHUB_PROMPT_SUBTITLE",
    "PROJECT_TOKEN_PASTE_TITLE",
    "PROJECT_TOKEN_PASTE_SUBTITLE",
    "PROJECT_TOKEN_REVIEW",
    "PROJECT_GITHUB_REUSE_LABEL",
    "PROJECT_GITHUB_REUSE_DESC",
    "PROJECT_GITHUB_STORE_LABEL",
    "PROJECT_GITHUB_STORE_DESC",
    "PROJECT_GITHUB_SKIP_LABEL",
    "PROJECT_GITHUB_SKIP_DESC",
    "PROJECT_TOKEN_ADOPTION_HELP",
]
