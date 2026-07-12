"""Git-side helpers for publishing an onboarded checkout to a new GitHub repo.

These complement :mod:`project_git_transport` (which owns ``run_git`` /
``https_remote``) with the publish-specific git operations: detecting whether a
checkout already has a repo or a remote, initializing one when needed, ensuring
an initial commit exists, and the create-then-push orchestration. The GitHub
REST write lives in :mod:`github_publish`; this module stitches it to git.

Onboarding runs every project git op over HTTPS, never SSH: the Textual wizard
owns the TTY, so an SSH host-key prompt on a fresh host would garble the UI and
deadlock. ``origin`` is the clean HTTPS URL with no embedded credential; the
push authenticates with the refreshed GitHub App user token carried as a
URL-scoped ``http.extraheader`` (never written to ``.git/config`` or the
stored remote).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import github_publish
from yoke_cli.config import onboard_checkout_ownership
from yoke_cli.config import project_git_branch
from yoke_cli.config import project_clone_resume
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config import project_local_git
from yoke_cli.config.project_git_process import NetworkGitBoundaryError
from yoke_cli.config.github_publish import GitHubPublishError
from yoke_cli.config.project_git_transport import https_remote, run_git
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_cli.config.project_publish_request import (
    PublishRequest,
    is_push_denied as _is_push_denied,
    post_create_push_failure_message as _post_create_push_failure_message,
)


def is_git_repo(root: Path) -> bool:
    """True when ``root`` is already inside a git work tree.

    A path that does not exist yet (a create-new checkout chosen before the
    folder is made) is not a repo — and running git there would raise — so the
    missing-directory case returns False rather than erroring.
    """
    if not root.is_dir():
        return False
    project_git_prerequisite.require_git_available()
    try:
        result = project_local_git.run(
            root,
            "rev-parse",
            "--is-inside-work-tree",
        )
    except (OSError, NetworkGitBoundaryError):
        return False
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
    try:
        result = project_local_git.run(root, "remote")
    except (OSError, NetworkGitBoundaryError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def publish_checkout_needed(root: Path, publish: "PublishRequest") -> bool:
    """True when apply should create/reuse the selected repo and push to it.

    A checkout with an unrelated remote keeps the existing "skip publish" behavior.
    A checkout whose ``origin`` already points at the selected repo is a resumable
    publish attempt: a prior run may have created the GitHub repo and added
    ``origin`` before the push failed, so apply should re-enter the create/reuse
    path and push again instead of silently skipping.
    """
    # An explicit publish request is never silently downgraded because a remote
    # appeared after Review. ``create_and_publish`` performs the exact origin
    # compatibility check before any GitHub write.
    return True


def init_repo_if_needed(root: Path, default_branch: str) -> bool:
    """Run ``git init`` on ``root`` only when it is not already a repo.

    Returns True when an init was performed. The local-checkout path may point
    at a plain folder; publishing needs a repo with a commit, so this lays the
    repo down first.
    """
    _require_branch(default_branch)
    if is_git_repo(root):
        return False
    run_git(root, "init", "--initial-branch", default_branch)
    onboard_checkout_ownership.mark_created(root)
    return True


def ensure_initial_commit(root: Path, default_branch: str) -> None:
    """Guarantee the checkout has at least one commit before a push.

    A freshly ``git init``-ed folder (or one with only uncommitted changes) has
    nothing to push. Stage everything and commit when ``HEAD`` is unborn; do
    nothing when a commit already exists.
    """
    _require_branch(default_branch)
    project_git_prerequisite.require_git_available()
    try:
        head = project_local_git.run(root, "rev-parse", "--verify", "HEAD")
    except (OSError, NetworkGitBoundaryError) as exc:
        raise ProjectOnboardError(
            "the local Git HEAD probe exceeded its safety boundary"
        ) from exc
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
    web_url: str | None = None,
) -> None:
    """Attach the created repo as HTTPS ``origin`` and push the default branch.

    Assumes the repo was already created on GitHub by the caller. A commit must
    exist for the push to land; the caller commits any pending tree first.
    ``origin`` is stored as the clean HTTPS URL; the push authenticates with
    ``token`` carried as a URL-scoped header (never persisted to the remote
    or ``.git/config``), so a private repo pushes without an interactive prompt.
    """
    _require_branch(default_branch)
    desired_remote = https_remote(github_repo, web_url=web_url)
    existing_origin = project_clone_resume.remote_url(root, "origin")
    if existing_origin:
        if not project_clone_resume.same_repo(
            existing_origin,
            desired_remote,
            web_url=web_url,
        ):
            raise ProjectOnboardError(
                "checkout already has a different origin remote; remove or "
                "rename it before publishing to "
                f"{github_repo}."
            )
    else:
        run_git(root, "remote", "add", "origin", desired_remote)
    run_git(
        root,
        "push",
        "-u",
        "origin",
        default_branch,
        token=token,
        github_web_url=web_url,
    )


def _require_branch(value: str) -> None:
    reason = project_git_branch.validation_error(value)
    if reason is not None:
        raise ProjectOnboardError(reason)


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
    if not publish.token:
        raise ProjectOnboardError(
            "GitHub App user authorization is required to publish this project"
        )
    root.mkdir(parents=True, exist_ok=True)
    init_repo_if_needed(root, default_branch)
    ensure_initial_commit(root, default_branch)
    desired_remote = https_remote(publish.full_name, web_url=publish.web_url)
    existing_origin = project_clone_resume.remote_url(root, "origin")
    if existing_origin and not project_clone_resume.same_repo(
        existing_origin,
        desired_remote,
        web_url=publish.web_url,
    ):
        raise ProjectOnboardError(
            "checkout already has a different origin remote; no GitHub "
            "repository was created or changed"
        )
    expected_head_sha = local_head_sha(root, default_branch)
    # Recheck after all local preparation and immediately before the remote
    # operation. This catches config drift without leaving an empty repository.
    current_origin = project_clone_resume.remote_url(root, "origin")
    if current_origin != existing_origin:
        raise ProjectOnboardError(
            "checkout origin changed while preparing publication; no GitHub "
            "repository was created or changed"
        )
    if not publish.create_repository:
        if (
            not isinstance(publish.repository_id, int)
            or publish.repository_id <= 0
            or not isinstance(publish.installation_id, int)
            or publish.installation_id <= 0
        ):
            raise ProjectOnboardError(
                "The selected existing repository identity is incomplete; "
                "check repositories again before Apply"
            )
        created = github_publish.verify_existing_repo(
            publish.api_url,
            publish.token,
            owner=publish.owner,
            name=publish.name,
            expected_head_sha=expected_head_sha,
            private=publish.private,
            repository_id=publish.repository_id,
            web_url=publish.web_url,
        )
    elif existing_origin:
        created = github_publish.verify_resumable_repo(
            publish.api_url,
            publish.token,
            owner=publish.owner,
            name=publish.name,
            private=publish.private,
            expected_head_sha=expected_head_sha,
            web_url=publish.web_url,
        )
    else:
        created = github_publish.create_repo(
            publish.api_url,
            publish.token,
            owner=publish.owner,
            name=publish.name,
            user_login=publish.user_login,
            private=publish.private,
            administration_allowed=publish.administration_allowed,
            web_url=publish.web_url,
        )
    full_name = created["full_name"]
    try:
        publish_to_remote(
            root,
            github_repo=full_name,
            default_branch=default_branch,
            token=publish.token,
            web_url=publish.web_url,
        )
    except ProjectOnboardError as exc:
        raise GitHubPublishError(
            _post_create_push_failure_message(
                full_name, exc, push_denied=_is_push_denied(str(exc))
            )
        ) from exc
    return created


def local_head_sha(root: Path, branch: str) -> str:
    """Return the exact local branch tip used to verify resumed remote content."""

    try:
        result = project_local_git.run(
            root,
            "rev-parse",
            "--verify",
            branch,
        )
    except (OSError, NetworkGitBoundaryError) as exc:
        raise ProjectOnboardError(
            "the local branch tip probe exceeded its safety boundary"
        ) from exc
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise ProjectOnboardError(
            "the local branch tip could not be verified for repository resume"
        )
    return value


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
