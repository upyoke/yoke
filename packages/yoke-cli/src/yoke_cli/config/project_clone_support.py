"""Clone-side git helpers for the onboarding "clone a project" flow.

The clone path supports three outcomes once the working copy exists — keep the
source as ``origin`` (just clone it), re-home onto a freshly created private
repo (make it mine), or fork the source and track it as ``upstream`` (fork it).
This module owns the git remote choreography for those outcomes plus the
private-clone token fallback.

Security invariants for the token fallback (enforced + tested):

* The connected token is passed to git only via ``-c http.extraheader=…`` on the
  single clone invocation. It is never written into the cloned repo's
  ``.git/config`` (``-c`` is request-scoped, not persisted), never baked into
  the stored ``origin`` URL, and never logged — the clone runner scrubs the
  header from any error it raises.
* SSH source URLs are normalized to their HTTPS form for the token clone (a
  token cannot authenticate an SSH transport), then ``origin`` is reset to the
  clean intended URL with no embedded credential.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from yoke_cli.config import project_clone_resume as clone_resume
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.project_clone_resume import (
    existing_clone_matches,
    origin_is,
)
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_cli.config.project_git_transport import (
    REDACTED_AUTH_HEADER,
    git_auth_header,
    git_current_branch,
    non_interactive_git_env,
    run_git,
)
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

_SSH_RE = re.compile(r"^git@github\.com:(?P<path>.+?)(?:\.git)?$")


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
    fallback_token: str | None = None
    fork_api_url: str = "https://api.github.com"


class CloneAccessError(ProjectOnboardError):
    """A clone failed for an access/auth reason that a token might rescue."""


def https_clone_url(remote_url: str) -> str:
    """Return the HTTPS clone URL for ``remote_url``.

    An ``https://`` URL is returned unchanged; an ``git@github.com:owner/repo``
    SSH URL is normalized to ``https://github.com/owner/repo.git`` so the token
    auth header can apply (a token cannot authenticate the SSH transport).
    """
    cleaned = remote_url.strip()
    match = _SSH_RE.match(cleaned)
    if match:
        return f"https://github.com/{match.group('path')}.git"
    return cleaned


def source_owner_repo(remote_url: str) -> tuple[str, str]:
    """Parse ``owner`` and ``repo`` from a GitHub source URL (SSH or HTTPS).

    Used to address the fork endpoint (``/repos/{owner}/{repo}/forks``). Raises
    when the URL is not a recognizable ``github.com`` owner/repo reference.
    """
    https = https_clone_url(remote_url).removesuffix(".git")
    marker = "github.com/"
    if marker in https:
        path = https.split(marker, 1)[1].strip("/")
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
    raise CloneAccessError(
        f"could not parse a github.com owner/repo from {remote_url!r}"
    )


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
    config: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Run ``git clone`` non-interactively under ``parent`` and capture output.

    Every ``config`` entry is passed as a TOP-LEVEL ``-c`` git option (placed
    BEFORE the ``clone`` subcommand) so it scopes to this single invocation and
    is NOT written into the cloned repo's ``.git/config`` — that placement is
    what keeps the auth header ephemeral. (``git clone -c …`` AFTER the
    subcommand would persist the config; that is the banned shape.) Credential
    prompting is disabled (``GIT_TERMINAL_PROMPT=0`` / ``core.askPass=``) so a
    private clone fails fast instead of hanging on a username prompt — that fast
    failure is what triggers the token fallback.
    """
    project_git_prerequisite.require_git_available()
    top_level: list[str] = ["-c", "core.askPass="]
    for entry in config:
        top_level += ["-c", entry]
    return subprocess.run(
        ["git", *top_level, "clone", url, name],
        cwd=parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=non_interactive_git_env(),
    )


@dataclass(frozen=True)
class CloneOutcome:
    """What the clone runner did, for the wizard's informational line.

    ``used_token`` is True only when the ambient clone failed and the token
    fallback then succeeded — that is the single case the wizard surfaces the
    "used your connected GitHub token" line for.
    """

    used_token: bool
    origin_url: str


def clone_with_token_fallback(
    parent: Path,
    name: str,
    remote_url: str,
    *,
    token: str | None,
) -> CloneOutcome:
    """Clone ``remote_url`` into ``parent/name``; on access failure retry with a token.

    The ambient-credential clone runs first. On an access/auth failure, when a
    token is connected, the source is normalized to HTTPS and re-cloned with the
    token as an ephemeral ``http.extraheader`` (request-scoped, never written to
    ``.git/config``); ``origin`` is then reset to the clean HTTPS URL so no
    credential is persisted. A failure even with the token raises a clear
    "token lacks access / repo not found" error.
    """
    ambient = _run_clone(parent, name, remote_url)
    if ambient.returncode == 0:
        return CloneOutcome(used_token=False, origin_url=remote_url)
    if not (token and _looks_like_access_failure(ambient.stderr)):
        raise CloneAccessError(
            "git clone failed: "
            + (ambient.stderr.strip() or ambient.stdout.strip() or "unknown error")
        )
    https_url = https_clone_url(remote_url)
    header = git_auth_header(token)
    fallback = _run_clone(
        parent, name, https_url, config=(f"http.extraheader={header}",),
    )
    if fallback.returncode != 0:
        # Scrub the header from the surfaced error so the encoded token can
        # never reach a log line.
        scrubbed = fallback.stderr.replace(header, REDACTED_AUTH_HEADER).strip()
        raise CloneAccessError(
            "clone failed even with your connected GitHub token — the token "
            "lacks access or the repo was not found: "
            + (scrubbed or "unknown error")
        )
    target = parent / name
    # The token traveled only in the -c request header; reset origin to the clean
    # HTTPS URL so no credential is persisted in the stored remote.
    run_git(target, "remote", "set-url", "origin", https_url)
    return CloneOutcome(used_token=True, origin_url=https_url)


def rehome_to_new_origin(
    root: Path,
    *,
    new_origin_url: str,
    default_branch: str | None = None,
    keep_upstream: bool,
    token: str | None = None,
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
    The push authenticates with ``token`` carried as a request-scoped header
    (never persisted to the remote or ``.git/config``), so the freshly created
    private repo pushes without an interactive prompt. Returns the branch pushed.

    Idempotent on a resume: when a prior run already re-pointed ``origin`` at
    ``new_origin_url``, the remote choreography is skipped and only the push is
    re-attempted (a no-op when the branch already landed) — so re-running after a
    push that failed mid-way completes the step instead of erroring on the
    already-renamed remote.
    """
    branch = git_current_branch(root)
    if not origin_is(root, new_origin_url):
        if keep_upstream and not clone_resume.remote_url(root, "upstream"):
            run_git(root, "remote", "rename", "origin", "upstream")
        elif not keep_upstream:
            run_git(root, "remote", "remove", "origin")
        run_git(root, "remote", "add", "origin", new_origin_url)
    run_git(root, "push", "-u", "origin", branch, token=token)
    return branch


def clone_progress_lines(repo: str, outcome: CloneOutcome) -> list[str]:
    """The approved informational lines for the clone step.

    A clean ambient clone shows the two-line "Cloning… / ✓ Cloned." pair; when
    the connected token rescued the clone, the middle line names that — honestly
    informational, never framed as an error. ``repo`` is the human-readable
    ``owner/repo`` derived from the clone URL.
    """
    lines = [f"  Cloning {repo}…"]
    if outcome.used_token:
        lines.append(
            "  Your git setup couldn't reach it — used your connected GitHub token."
        )
    lines.append("  ✓ Cloned.")
    return lines


def set_fork_remotes(root: Path, *, fork_url: str) -> None:
    """Point ``origin`` at the user's fork and track the source as ``upstream``.

    The fresh clone has the source as ``origin``; the fork flow renames that to
    ``upstream`` (so the source stays reachable for pulling updates and opening
    pull requests back) and adds the fork as the new ``origin``.

    Idempotent on a resume: when ``origin`` already points at the fork, the
    remote choreography is skipped so re-running after a partial fork doesn't
    error on the already-renamed remote.
    """
    if origin_is(root, fork_url):
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
