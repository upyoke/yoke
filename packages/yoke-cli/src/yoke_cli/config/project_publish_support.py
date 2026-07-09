"""Git-side helpers for publishing an onboarded checkout to a new GitHub repo.

These complement :mod:`project_git_transport` (which owns ``run_git`` /
``https_remote``) with the publish-specific git operations: detecting whether a
checkout already has a repo or a remote, initializing one when needed, ensuring
an initial commit exists, and the create-then-push orchestration. The GitHub
REST write lives in :mod:`github_publish`; this module stitches it to git.

Onboarding runs every project git op over HTTPS, never SSH: the Textual wizard
owns the TTY, so an SSH host-key prompt on a fresh host would garble the UI and
deadlock. ``origin`` is the clean HTTPS URL with no embedded credential; the
push authenticates with the refreshed GitHub App user token carried as a single
request-scoped ``http.extraheader`` (never written to ``.git/config`` or the
stored remote).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yoke_cli.config import github_publish
from yoke_cli.config import project_clone_resume
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.github_publish import GitHubPublishError
from yoke_cli.config.project_git_transport import https_remote, run_git
from yoke_cli.config.project_onboard_support import ProjectOnboardError

# Substrings (case-insensitive) that mark a git/GitHub push or write denial for
# a GitHub App user authorization that cannot push to the created repo. Used to
# convert the raw git failure into a typed, repo-naming GitHubPublishError at
# the publish seam.
_PUSH_DENIED_SIGNATURES = (
    "write access to repository not granted",
    "permission to",  # "Permission to X denied"
    "http 403",
    "error: 403",
)


def _is_push_denied(message: str) -> bool:
    low = message.lower()
    return any(signature in low for signature in _PUSH_DENIED_SIGNATURES)


def is_git_repo(root: Path) -> bool:
    """True when ``root`` is already inside a git work tree.

    A path that does not exist yet (a create-new checkout chosen before the
    folder is made) is not a repo — and running git there would raise — so the
    missing-directory case returns False rather than erroring.
    """
    if not root.is_dir():
        return False
    project_git_prerequisite.require_git_available()
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def is_existing_project_dir(root: Path) -> bool:
    """True when ``root`` already holds a project — a git repo or non-empty dir.

    "Create a new project" makes a fresh folder. If the user points it at a
    folder that already exists with content (or is already a git repo), that is
    really the "existing folder" case, so the create-new flow redirects there
    instead of trying to create over existing code. A missing or empty folder
    is a fine create-new target and returns False.
    """
    if is_git_repo(root):
        return True
    try:
        return root.is_dir() and any(root.iterdir())
    except OSError:
        return False


def has_remote(root: Path) -> bool:
    """True when the checkout already has at least one configured git remote.

    The publish step is auto-skipped for checkouts that already point at a
    remote — re-homing an existing remote is a separate capability.
    """
    if not is_git_repo(root):
        return False
    result = subprocess.run(
        ["git", "remote"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def publish_checkout_needed(root: Path, publish: "PublishRequest") -> bool:
    """True when apply should create/reuse the selected repo and push to it.

    A checkout with an unrelated remote keeps the existing "skip publish" behavior.
    A checkout whose ``origin`` already points at the selected repo is a resumable
    publish attempt: a prior run may have created the GitHub repo and added
    ``origin`` before the push failed, so apply should re-enter the create/reuse
    path and push again instead of silently skipping.
    """
    if not has_remote(root):
        return True
    return project_clone_resume.origin_is(root, https_remote(publish.full_name))


def init_repo_if_needed(root: Path, default_branch: str) -> bool:
    """Run ``git init`` on ``root`` only when it is not already a repo.

    Returns True when an init was performed. The local-checkout path may point
    at a plain folder; publishing needs a repo with a commit, so this lays the
    repo down first.
    """
    if is_git_repo(root):
        return False
    run_git(root, "init", "--initial-branch", default_branch)
    return True


def ensure_initial_commit(root: Path, default_branch: str) -> None:
    """Guarantee the checkout has at least one commit before a push.

    A freshly ``git init``-ed folder (or one with only uncommitted changes) has
    nothing to push. Stage everything and commit when ``HEAD`` is unborn; do
    nothing when a commit already exists.
    """
    project_git_prerequisite.require_git_available()
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if head.returncode == 0:
        return
    run_git(root, "checkout", "-B", default_branch)
    run_git(root, "add", "-A")
    run_git(root, "commit", "--allow-empty", "-m", "Initial commit")


def publish_to_remote(
    root: Path,
    *,
    github_repo: str,
    default_branch: str,
    token: str | None = None,
) -> None:
    """Attach the created repo as HTTPS ``origin`` and push the default branch.

    Assumes the repo was already created on GitHub by the caller. A commit must
    exist for the push to land; the caller commits any pending tree first.
    ``origin`` is stored as the clean HTTPS URL; the push authenticates with
    ``token`` carried as a request-scoped header (never persisted to the remote
    or ``.git/config``), so a private repo pushes without an interactive prompt.
    """
    desired_remote = https_remote(github_repo)
    existing_origin = project_clone_resume.remote_url(root, "origin")
    if existing_origin:
        if not project_clone_resume.same_repo(existing_origin, desired_remote):
            raise ProjectOnboardError(
                "checkout already has an origin remote "
                f"({existing_origin}); remove or rename it before publishing to "
                f"{github_repo}."
            )
    else:
        run_git(root, "remote", "add", "origin", desired_remote)
    run_git(root, "push", "-u", "origin", default_branch, token=token)


@dataclass(frozen=True)
class PublishRequest:
    """Inputs for creating a GitHub repo and pushing the checkout to it.

    Carried from the wizard's "Also publish to GitHub?" answer: the owner the
    user picked, the repo name, and the App user token/api that the create call
    authenticates with. ``user_login`` selects the user-vs-org create endpoint.
    """

    owner: str
    name: str
    user_login: str
    token: str
    api_url: str = "https://api.github.com"
    private: bool = True

    @property
    def full_name(self) -> str:
        """The selected GitHub repo as ``owner/name``."""
        return f"{self.owner}/{self.name}"


def create_and_publish(
    root: Path,
    publish: PublishRequest,
    *,
    default_branch: str,
) -> dict[str, Any]:
    """Create the repo on GitHub, then init/commit/push the checkout to it.

    Returns the created-repo summary. The checkout is guaranteed to be a git
    repo with at least one commit before the push; ``origin`` is then attached
    and the default branch pushed with upstream tracking.
    """
    project_git_prerequisite.require_git_available()
    created = github_publish.create_repo(
        publish.api_url,
        publish.token,
        owner=publish.owner,
        name=publish.name,
        user_login=publish.user_login,
        private=publish.private,
    )
    init_repo_if_needed(root, default_branch)
    ensure_initial_commit(root, default_branch)
    full_name = created["full_name"]
    try:
        publish_to_remote(
            root, github_repo=full_name, default_branch=default_branch,
            token=publish.token,
        )
    except ProjectOnboardError as exc:
        raise GitHubPublishError(
            _post_create_push_failure_message(
                full_name, exc, push_denied=_is_push_denied(str(exc))
            )
        ) from exc
    return created


def _post_create_push_failure_message(
    full_name: str,
    exc: ProjectOnboardError,
    *,
    push_denied: bool,
) -> str:
    if push_denied:
        return (
            f"GitHub created {full_name}, but this token couldn't push to it. "
            "The repo is empty — delete it on GitHub, then re-run and choose "
            "Clone or an existing folder."
        )
    return (
        f"GitHub created {full_name}, but the push did not finish: {exc}. "
        "Fix the connection or GitHub availability, then re-run yoke onboard "
        f"to resume the push. To start over instead, delete {full_name} on "
        "GitHub first."
    )


__all__ = [
    "GitHubPublishError",
    "PublishRequest",
    "create_and_publish",
    "ensure_initial_commit",
    "has_remote",
    "init_repo_if_needed",
    "is_existing_project_dir",
    "is_git_repo",
    "publish_checkout_needed",
    "publish_to_remote",
]
