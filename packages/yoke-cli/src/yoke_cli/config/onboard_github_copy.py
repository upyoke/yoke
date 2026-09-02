"""Shared user-facing copy for GitHub App onboarding screens."""

from __future__ import annotations

MACHINE_GITHUB_TITLE = "Connect GitHub?"
MACHINE_GITHUB_SUBTITLE = (
    "Use the Yoke GitHub App for Issues, merge queue, and App CI, or skip "
    "and keep local merge."
)
MACHINE_GITHUB_REVIEW = "Connect this machine through the Yoke GitHub App"
MACHINE_GITHUB_SKIP_LABEL = "Skip GitHub"
MACHINE_GITHUB_SKIP_DESC = (
    "local merge; no Issues, merge queue, or App CI"
)
MACHINE_GITHUB_SKIP_REVIEW = (
    "Skip GitHub — local merge; Issues, merge queue, and App CI stay off"
)

PROJECT_GITHUB_PROMISE = (
    "Bind this project to a GitHub App repository, or skip — local backlog "
    "and merge stay; Issues, merge queue, and App CI stay off."
)

PROJECT_GITHUB_PROMPT_TITLE = "How should Yoke manage this project on GitHub?"
PROJECT_GITHUB_PROMPT_SUBTITLE = PROJECT_GITHUB_PROMISE

PROJECT_GITHUB_ACCESS_TITLE = "GitHub App repo binding is required."
PROJECT_GITHUB_ACCESS_SUBTITLE = (
    "Use a repository already available to the Yoke GitHub App, add repository "
    "access in GitHub, or skip and keep local backlog and merge."
)

PROJECT_GITHUB_REVIEW = (
    "Bind this project to a GitHub App repository for Issues, PRs, CI, and Actions"
)

PROJECT_GITHUB_REUSE_LABEL = "Use connected repo"
PROJECT_GITHUB_REUSE_DESC = "bind this repo using existing App access"
PROJECT_GITHUB_STORE_LABEL = "Add repo access"
PROJECT_GITHUB_STORE_DESC = "open GitHub to change app access"
PROJECT_GITHUB_SKIP_LABEL = "Skip GitHub for this project"
PROJECT_GITHUB_SKIP_DESC = (
    "local backlog and merge; no Issues, merge queue, or App CI"
)
PROJECT_GITHUB_SKIP_REVIEW = (
    "Keep the project local — backlog and merge stay here; GitHub "
    "automation stays off"
)

PROJECT_GITHUB_SETUP_HELP = (
    "Project GitHub automation now uses a Yoke GitHub App repo binding. "
    "Bind the selected repository, add App access, or skip and keep local "
    "backlog and merge."
)

CLONE_FROM_GITHUB_LABEL = "Clone a project from GitHub"
CLONE_FROM_GITHUB_DESC = "GitHub URL only — not GitLab or Bitbucket"
CLONE_FROM_GITHUB_TITLE = "Clone a project from GitHub."
CLONE_FROM_GITHUB_SUBTITLE = (
    "Paste a GitHub repo URL. GitLab and Bitbucket are not clone sources."
)
CLONE_VISIBILITY_PUBLIC_DESC = "paste a GitHub URL"

CLONE_CONNECT_RECOVERY = (
    "Run `yoke github connect` so `yoke github status` reports ready=true, "
    "or choose Connect GitHub in this wizard."
)
CLONE_MISSING_AUTHORIZATION = (
    "Yoke couldn't read that GitHub repo because this machine has no usable "
    "GitHub authorization (`yoke github status` reports ready=false). "
    + CLONE_CONNECT_RECOVERY
)


__all__ = [
    "MACHINE_GITHUB_TITLE",
    "MACHINE_GITHUB_SUBTITLE",
    "MACHINE_GITHUB_REVIEW",
    "MACHINE_GITHUB_SKIP_LABEL",
    "MACHINE_GITHUB_SKIP_DESC",
    "MACHINE_GITHUB_SKIP_REVIEW",
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
    "PROJECT_GITHUB_SKIP_REVIEW",
    "PROJECT_GITHUB_SETUP_HELP",
    "CLONE_FROM_GITHUB_LABEL",
    "CLONE_FROM_GITHUB_DESC",
    "CLONE_FROM_GITHUB_TITLE",
    "CLONE_FROM_GITHUB_SUBTITLE",
    "CLONE_VISIBILITY_PUBLIC_DESC",
    "CLONE_CONNECT_RECOVERY",
    "CLONE_MISSING_AUTHORIZATION",
]
