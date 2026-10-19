"""Shared user-facing copy for GitHub App onboarding screens."""

from __future__ import annotations

MACHINE_GITHUB_TITLE = "Connect GitHub?"
MACHINE_GITHUB_SUBTITLE = (
    "Use the Yoke GitHub App for Issues, merge queue, and App CI, or skip "
    "and keep local merge."
)
MACHINE_GITHUB_REVIEW = "Connect this machine through the Yoke GitHub App"
MACHINE_GITHUB_SKIP_LABEL = "Skip GitHub"
MACHINE_GITHUB_SKIP_DESC = "local merge; no Issues, merge queue, or App CI"
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
    "Bind this project to a GitHub App repository for PRs, CI, and Actions"
)

PROJECT_GITHUB_REUSE_LABEL = "Use connected repo"
PROJECT_GITHUB_REUSE_DESC = "bind this repo using existing App access"
PROJECT_GITHUB_STORE_LABEL = "Add repo access"
PROJECT_GITHUB_STORE_DESC = "open GitHub to change app access"
PROJECT_GITHUB_SKIP_LABEL = "Skip GitHub for this project"
PROJECT_GITHUB_SKIP_DESC = "local backlog and merge; no Issues, merge queue, or App CI"
PROJECT_GITHUB_SKIP_REVIEW = (
    "Keep the project local — backlog and merge stay here; GitHub automation stays off"
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


OTHER_PROVIDER_SENTENCE = (
    "Yoke supports GitHub only for now; it works without the GitHub connection,"
)
GITHUB_SIGN_UP_MODES = ("create-repo", "clone-remote", "import-remote")


def machine_github_agent_guidance(project_mode: str | None) -> str:
    """How an agent answers the machine GitHub question for this run."""
    sign_up = (
        " This work uses GitHub, so if the person has no account, offer signing "
        "up at github.com before answering connect."
        if project_mode in GITHUB_SIGN_UP_MODES
        else ""
    )
    return (
        "Ask whether the person uses GitHub. With a GitHub account, answer "
        "connect and pass the browser link to the person. With no GitHub "
        "account, explain that setup continues without it and answer skip. "
        f'With another source-control provider, say "{OTHER_PROVIDER_SENTENCE}" '
        f"then answer skip.{sign_up}"
    )


PROJECT_GITHUB_AGENT_GUIDANCE = (
    "Answer reuse-machine when the machine GitHub connection is saved and the "
    "person wants this project on it. With no GitHub account or another "
    f'source-control provider, say "{OTHER_PROVIDER_SENTENCE}" then answer skip. '
    "Binding leaves issue sync off. Only if mirroring the backlog to GitHub "
    "Issues is useful for this project, explain it and offer a separate opt-in "
    "after setup. Enable only with their agreement, using the project update "
    "recipe in .yoke/docs/github/sync.md; never infer agreement from "
    "connecting GitHub or approving setup."
)
PROJECT_MODE_AGENT_GUIDANCE = (
    "Ask the person where their code lives. Answer machine-only if they have no "
    "project yet; clone-remote clones from GitHub, which needs a GitHub "
    "account."
)
DESTINATION_AGENT_GUIDANCE = (
    "Ask where the person's Yoke data should live. Answer local for one person "
    "on this machine, server when their team runs a Yoke server and they have "
    "its URL, and hosted only when they have upyoke.com access."
)

__all__ = [
    "DESTINATION_AGENT_GUIDANCE",
    "GITHUB_SIGN_UP_MODES",
    "OTHER_PROVIDER_SENTENCE",
    "PROJECT_GITHUB_AGENT_GUIDANCE",
    "PROJECT_MODE_AGENT_GUIDANCE",
    "machine_github_agent_guidance",
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
