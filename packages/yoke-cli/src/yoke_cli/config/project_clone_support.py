"""Clone-side git helpers for the onboarding "clone a project" flow.

The clone path supports three outcomes once the working copy exists — keep the
source as ``origin`` (just clone it), re-home onto a freshly created private
repo (make it mine), or fork the source and track it as ``upstream`` (fork it).
This module owns the git remote choreography for those outcomes plus the
private-clone token fallback.

Security invariants for the token fallback (enforced + tested):

* The connected token is passed to git only via URL-scoped, ephemeral
  ``GIT_CONFIG_*`` subprocess variables. It is never exposed in argv or written
  into the cloned repo's ``.git/config``, never baked into
  the stored ``origin`` URL, and never logged — the clone runner scrubs the
  header from any error it raises.
* SSH source URLs are normalized to their HTTPS form for the token clone (a
  token cannot authenticate an SSH transport), then ``origin`` is reset to the
  clean intended URL with no embedded credential.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from yoke_contracts import github_origin
from yoke_cli.config import project_clone_resume as clone_resume
from yoke_cli.config.project_clone_progress import clone_progress_lines
from yoke_cli.config import project_clone_runner
from yoke_cli.config.project_clone_resume import (
    existing_clone_matches,
    origin_is,
)
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_cli.config.project_git_transport import (
    clean_remote_url,
    git_current_branch,
    isolated_remote_config,
    is_configured_github_remote,
    run_git,
)
from yoke_cli.config.project_git_diagnostics import scrub_git_diagnostic
from yoke_cli.config.project_git_process import run_network_git
from yoke_cli.config.project_publish_support import PublishRequest

# The three post-clone outcomes the wizard offers. ``just-clone`` leaves origin
# pointing at the source; ``make-it-mine`` re-homes onto a new private repo;
# ``fork`` forks the source and tracks it as upstream.
CLONE_OUTCOME_JUST_CLONE = "just-clone"
CLONE_OUTCOME_MAKE_IT_MINE = "make-it-mine"
CLONE_OUTCOME_FORK = "fork"
CLONE_OUTCOMES = (
    CLONE_OUTCOME_JUST_CLONE,
    CLONE_OUTCOME_MAKE_IT_MINE,
    CLONE_OUTCOME_FORK,
)

@dataclass(frozen=True)
class ClonePlan:
    """The post-clone decision threaded from the wizard into ``import_project``.

    ``outcome`` selects the remote choreography. ``keep_upstream`` is honored
    only by ``make-it-mine``, where it always keeps the source as a pull-only
    ``upstream`` remote so a private copy can still pull from a public original.
    ``publish`` carries the GitHub repo-create inputs for ``make-it-mine``;
    ``fallback_token`` is the refreshed GitHub App user token the private-clone
    fallback and the fork call authenticate with.
    """

    outcome: str = CLONE_OUTCOME_JUST_CLONE
    keep_upstream: bool = True
    publish: PublishRequest | None = None
    fallback_token: str | None = field(default=None, repr=False)
    use_machine_github: bool = False
    fork_api_url: str = github_origin.DEFAULT_GITHUB_API_URL
    fork_web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL
    fork_allowed: bool = False


class CloneAccessError(ProjectOnboardError):
    """A clone failed for an access/auth reason that a token might rescue."""


def https_clone_url(remote_url: str, *, web_url: str | None = None) -> str:
    """Return the HTTPS clone URL for ``remote_url``.

    An ``https://`` URL is returned unchanged; an ``git@github.com:owner/repo``
    SSH URL is normalized to ``https://github.com/owner/repo.git`` so the token
    auth header can apply (a token cannot authenticate the SSH transport).
    """
    try:
        return clean_remote_url(remote_url, web_url=web_url)
    except ProjectOnboardError as exc:
        raise CloneAccessError(str(exc)) from exc


def source_owner_repo(
    remote_url: str, *, web_url: str | None = None,
) -> tuple[str, str]:
    """Parse ``owner`` and ``repo`` from a GitHub source URL (SSH or HTTPS).

    Used to address the fork endpoint (``/repos/{owner}/{repo}/forks``). Raises
    when the URL is not a recognizable ``github.com`` owner/repo reference.
    """
    try:
        repo = github_origin.normalize_github_repository(
            remote_url, web_url=web_url,
        )
    except github_origin.GitHubApiOriginError as exc:
        raise CloneAccessError(str(exc)) from exc
    return tuple(repo.split("/", 1))


def _looks_like_access_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    needles = (
        "authentication failed",
        "could not read username",
        "permission denied",
        "access denied",
        "repository not found",
        "fatal: could not read",
        "terminal prompts disabled",
        "403",
        "401",
    )
    return any(needle in lowered for needle in needles)


def _run_clone(
    parent: Path,
    name: str,
    url: str,
    *,
    token: str | None = None,
    github_web_url: str | None = None,
    target_claim: project_clone_runner.CloneTargetClaim | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``git clone`` non-interactively under ``parent`` and capture output.

    Every ``config`` entry is passed through ephemeral ``GIT_CONFIG_*``
    subprocess variables, so no secret appears in argv or the clone's config. Credential
    prompting is disabled (``GIT_TERMINAL_PROMPT=0`` / ``core.askPass=``) so a
    private clone fails fast instead of hanging on a username prompt — that fast
    failure is what triggers the token fallback.
    """
    try:
        clean_url = clean_remote_url(url, web_url=github_web_url)
        config = isolated_remote_config(
            clean_url, token=token, web_url=github_web_url,
        )
    except ProjectOnboardError as exc:
        raise CloneAccessError(str(exc)) from exc
    return project_clone_runner.run_clone(
        parent=parent,
        name=name,
        clean_url=clean_url,
        config=config,
        token=token,
        runner=run_network_git,
        error_type=CloneAccessError,
        target_claim=target_claim,
    )


@dataclass(frozen=True)
class CloneOutcome:
    """What the clone runner did, for the wizard's informational line.

    ``used_token`` is True only when the anonymous clone failed and App-authorized
    fallback then succeeded — that is the single case the wizard surfaces its
    connected GitHub App access line for.
    """

    used_token: bool
    origin_url: str


def clone_with_token_fallback(
    parent: Path,
    name: str,
    remote_url: str,
    *,
    token: str | None = None,
    token_provider: Callable[[], str | None] | None = None,
    github_web_url: str | None = None,
) -> CloneOutcome:
    """Clone ``remote_url`` into ``parent/name``; on access failure retry with a token.

    A deliberately anonymous, helper-free clone runs first. On an access/auth
    failure, when a
    token is connected, the source is normalized to HTTPS and re-cloned with the
    token as a URL-scoped ephemeral ``http.extraheader`` (never written to
    ``.git/config``); ``origin`` is then reset to the clean HTTPS URL so no
    credential is persisted. A failure even with the token raises a clear
    "token lacks access / repo not found" error.
    """
    https_url = https_clone_url(remote_url, web_url=github_web_url)
    target = parent / name
    target_claim = project_clone_runner.CloneTargetClaim()
    anonymous = _run_clone(
        parent, name, https_url, github_web_url=github_web_url,
        target_claim=target_claim,
    )
    if anonymous.returncode == 0:
        return CloneOutcome(used_token=False, origin_url=https_url)
    if not is_configured_github_remote(
        https_url, web_url=github_web_url,
    ):
        detail = scrub_git_diagnostic(
            anonymous.stderr.strip()
            or anonymous.stdout.strip()
            or "unknown error",
        )
        raise CloneAccessError(
            f"git clone could not reach {https_url} anonymously; GitHub App "
            "authorization is never sent to external HTTPS repositories: "
            f"{detail}"
        )
    if (
        not _looks_like_access_failure(anonymous.stderr)
        and not token
        and token_provider is None
    ):
        raise CloneAccessError(
            "git clone failed: "
            + scrub_git_diagnostic(
                anonymous.stderr.strip()
                or anonymous.stdout.strip()
                or "unknown error",
            )
        )
    if not token and token_provider is not None:
        token = token_provider()
    if not token:
        raise CloneAccessError(
            "git clone could not access the repository anonymously; connect "
            "the Yoke GitHub App for private repository access"
        )
    fallback = _run_clone(
        parent, name, https_url,
        token=token,
        github_web_url=github_web_url,
        target_claim=target_claim,
    )
    if fallback.returncode != 0:
        scrubbed = scrub_git_diagnostic(fallback.stderr, token=token)
        raise CloneAccessError(
            "clone failed even with connected GitHub App access — the App "
            "authorization lacks access or the repo was not found: "
            + (scrubbed or "unknown error")
        )
    # The token traveled only through URL-scoped GIT_CONFIG_*; reset origin to
    # the clean HTTPS URL so no credential is persisted in the stored remote.
    run_git(target, "remote", "set-url", "origin", https_url)
    # The authenticated clone deliberately used --no-checkout: checkout runs in
    # this second, token-free process so hooks and content filters can never
    # inherit the ephemeral Authorization config.
    run_git(target, "checkout", "-f")
    return CloneOutcome(used_token=True, origin_url=https_url)


def rehome_to_new_origin(
    root: Path,
    *,
    new_origin_url: str,
    default_branch: str | None = None,
    keep_upstream: bool,
    token: str | None = None,
    github_web_url: str | None = None,
) -> str:
    """Re-point ``origin`` at a repo the user owns, keeping or dropping the source.

    The source remote currently named ``origin`` becomes ``upstream`` (when
    ``keep_upstream``) or is removed (a clean copy); ``origin`` is then set to
    ``new_origin_url`` (a clean HTTPS URL) and the cloned repo's CURRENT branch
    pushed with upstream tracking. The branch is detected from the working copy
    rather than assumed to be ``default_branch``: a cloned source repo checks out
    whatever its HEAD points at (often ``master`` or a project-specific default),
    so pushing a hardcoded ``main`` would fail with ``src refspec main does not
    match any`` and abort onboarding. ``default_branch`` is retained as an
    optional caller hint but the pushed/returned branch is always the live one.
    The push authenticates with ``token`` carried as a URL-scoped header
    (never persisted to the remote or ``.git/config``), so the freshly created
    private repo pushes without an interactive prompt. Returns the branch pushed.

    Idempotent on a resume: when a prior run already re-pointed ``origin`` at
    ``new_origin_url``, the remote choreography is skipped and only the push is
    re-attempted (a no-op when the branch already landed) — so re-running after a
    push that failed mid-way completes the step instead of erroring on the
    already-renamed remote.
    """
    branch = git_current_branch(root)
    if not origin_is(root, new_origin_url, web_url=github_web_url):
        if keep_upstream and not clone_resume.remote_url(root, "upstream"):
            run_git(root, "remote", "rename", "origin", "upstream")
        elif not keep_upstream:
            run_git(root, "remote", "remove", "origin")
        run_git(root, "remote", "add", "origin", new_origin_url)
    run_git(
        root, "push", "-u", "origin", branch,
        token=token, github_web_url=github_web_url,
    )
    return branch


def set_fork_remotes(
    root: Path,
    *,
    fork_url: str,
    github_web_url: str | None = None,
) -> None:
    """Point ``origin`` at the user's fork and track the source as ``upstream``.

    The fresh clone has the source as ``origin``; the fork flow renames that to
    ``upstream`` (so the source stays reachable for pulling updates and opening
    pull requests back) and adds the fork as the new ``origin``.

    Idempotent on a resume: when ``origin`` already points at the fork, the
    remote choreography is skipped so re-running after a partial fork doesn't
    error on the already-renamed remote.
    """
    if origin_is(root, fork_url, web_url=github_web_url):
        return
    if not clone_resume.remote_url(root, "upstream"):
        run_git(root, "remote", "rename", "origin", "upstream")
    elif clone_resume.remote_url(root, "origin"):
        run_git(root, "remote", "remove", "origin")
    run_git(root, "remote", "add", "origin", fork_url)


__all__ = [
    "CLONE_OUTCOMES",
    "CLONE_OUTCOME_FORK",
    "CLONE_OUTCOME_JUST_CLONE",
    "CLONE_OUTCOME_MAKE_IT_MINE",
    "CloneAccessError",
    "CloneOutcome",
    "ClonePlan",
    "clone_progress_lines",
    "clone_with_token_fallback",
    "existing_clone_matches",
    "https_clone_url",
    "origin_is",
    "rehome_to_new_origin",
    "set_fork_remotes",
    "source_owner_repo",
]
