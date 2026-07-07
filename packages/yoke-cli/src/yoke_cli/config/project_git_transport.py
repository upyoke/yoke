"""Non-interactive HTTPS git transport for project onboarding.

Onboarding runs every project git operation over HTTPS, never SSH: the Textual
wizard owns the TTY, so an SSH host-key prompt on a fresh host (no ``known_hosts``)
would garble the UI, swallow the user's "yes", and deadlock onboarding. This
module is the single home for that transport policy:

* :func:`https_remote` builds the clean HTTPS ``origin`` URL — no embedded
  credential.
* :func:`git_auth_header` encodes the connected token as a request-scoped HTTP
  Basic header (``x-access-token:<TOKEN>``) — the single source of the encoding
  shared by the clone-side and push-side runners.
* :func:`non_interactive_git_env` builds a git subprocess env that can never
  block on a prompt (``GIT_TERMINAL_PROMPT=0`` plus a ``BatchMode``/``accept-new``
  ``GIT_SSH_COMMAND`` for any residual SSH path).
* :func:`run_git` runs a git command under that env, optionally injecting the
  token as a single top-level ``-c http.extraheader=…`` option that is never
  written to ``.git/config`` or the stored remote and is scrubbed from any
  raised error.
"""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from typing import Mapping

from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.project_onboard_support import ProjectOnboardError

# The redaction placeholder substituted for the auth header in any surfaced
# error so a token can never reach a log line (same invariant the clone runner
# enforces).
REDACTED_AUTH_HEADER = "AUTHORIZATION: basic [redacted]"


def https_remote(github_repo: str) -> str:
    """Return the clean HTTPS remote URL for ``owner/repo``.

    The returned URL is the stored ``origin`` — clean, with no embedded
    credential; the connected token travels separately as a request-scoped
    ``http.extraheader`` (see :func:`git_auth_header`). HTTPS is used because the
    wizard owns the TTY and an SSH host-key prompt would deadlock onboarding.
    """
    return f"https://github.com/{github_repo}.git"


def git_auth_header(token: str) -> str:
    """Build the ``http.extraheader`` value carrying the token as HTTP Basic.

    GitHub accepts ``x-access-token:<TOKEN>`` base64-encoded as Basic auth. The
    value is consumed by a single ``-c http.extraheader=…`` top-level git option
    and never persisted to ``.git/config`` or the stored remote. Single source of
    the encoding so the clone-side runner and the push-side runner agree.
    """
    encoded = base64.b64encode(
        f"x-access-token:{token}".encode("utf-8")
    ).decode("ascii")
    return f"AUTHORIZATION: basic {encoded}"


def non_interactive_git_env(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a git subprocess env that can never block on an interactive prompt.

    ``GIT_TERMINAL_PROMPT=0`` makes git fail fast instead of prompting for a
    username/password (the TUI holds the terminal, so a prompt would garble the
    UI and deadlock). ``GIT_SSH_COMMAND`` hardens the residual-SSH case
    (``BatchMode=yes`` refuses any SSH prompt; ``StrictHostKeyChecking=accept-new``
    auto-trusts an unknown host-key instead of asking) — though onboarding
    eliminates SSH for github.com entirely in favor of HTTPS + the token header.
    """
    env = dict(base if base is not None else os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault(
        "GIT_SSH_COMMAND",
        "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
    )
    return env


def run_git(cwd: Path, *args: str, token: str | None = None) -> None:
    """Run a git command non-interactively, optionally with the ephemeral token.

    Always runs under :func:`non_interactive_git_env` so no git op can hang on a
    credential or host-key prompt while the wizard owns the terminal. When
    ``token`` is given, it is injected as a single TOP-LEVEL
    ``-c http.extraheader=…`` option (placed BEFORE the subcommand) so it scopes
    to this one invocation and is never written into ``.git/config`` or the
    stored remote; the header is scrubbed from any raised error so the encoded
    token can never reach a log line.
    """
    try:
        project_git_prerequisite.require_git_available()
    except project_git_prerequisite.MissingGitError as exc:
        raise ProjectOnboardError(str(exc)) from exc
    top_level: list[str] = []
    header: str | None = None
    if token:
        header = git_auth_header(token)
        top_level = ["-c", f"http.extraheader={header}"]
    result = subprocess.run(
        ["git", *top_level, *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=non_interactive_git_env(),
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        if header:
            detail = detail.replace(header, REDACTED_AUTH_HEADER)
        raise ProjectOnboardError(
            f"git {' '.join(args)} failed with {result.returncode}: {detail}"
        )


def remote_default_branch(url: str, token: str | None = None) -> str | None:
    """Return the default branch of the remote ``url`` without cloning it.

    Runs ``git ls-remote --symref <url> HEAD`` non-interactively and parses the
    symref line (``ref: refs/heads/<branch>\\tHEAD``) so a clone of a ``master``
    (or any non-``main``) source records the source's real default branch instead
    of a hardcoded guess. ``token`` is injected as the same request-scoped
    ``http.extraheader`` :func:`run_git` uses, so a private source is reachable
    without an interactive prompt. Returns ``None`` on any failure (network down,
    auth refused, unparseable output, no symref line) so the wizard can fall back
    to a plain default rather than crash on a probe.
    """
    cleaned = url.strip()
    if not cleaned:
        return None
    project_git_prerequisite.require_git_available()
    top_level: list[str] = []
    if token:
        top_level = ["-c", f"http.extraheader={git_auth_header(token)}"]
    try:
        result = subprocess.run(
            ["git", *top_level, "ls-remote", "--symref", cleaned, "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=non_interactive_git_env(),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        # The symref line looks like: ``ref: refs/heads/main\tHEAD``.
        stripped = line.strip()
        if not stripped.startswith("ref:"):
            continue
        ref = stripped[len("ref:"):].split("\t", 1)[0].strip()
        prefix = "refs/heads/"
        if ref.startswith(prefix):
            branch = ref[len(prefix):].strip()
            if branch:
                return branch
    return None


def remote_is_reachable(url: str, token: str | None = None) -> bool:
    """True when the remote ``url`` answers a metadata probe with the given auth.

    A thin wrapper over the same ``ls-remote`` probe :func:`remote_default_branch`
    runs: it confirms the repo exists and the credentials (ambient or ``token``)
    can read it, so the wizard can reject an unreachable URL inline instead of
    deferring the failure to a clone at apply. Returns ``False`` on any failure.
    """
    cleaned = url.strip()
    if not cleaned:
        return False
    project_git_prerequisite.require_git_available()
    top_level: list[str] = []
    if token:
        top_level = ["-c", f"http.extraheader={git_auth_header(token)}"]
    try:
        result = subprocess.run(
            ["git", *top_level, "ls-remote", cleaned, "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=non_interactive_git_env(),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def git_current_branch(cwd: Path) -> str:
    """Return the name of the currently checked-out branch in ``cwd``.

    A freshly cloned repo checks out whatever branch the source repo's HEAD
    points at — ``master``, ``main``, ``trunk``, or anything else — so the
    re-home push must target that branch rather than assuming ``main`` (a wrong
    assumption fails with ``src refspec main does not match any``). Runs under
    :func:`non_interactive_git_env` like :func:`run_git`; raises
    :class:`ProjectOnboardError` when the branch cannot be resolved (e.g. a
    detached HEAD or an empty repo with no commits).
    """
    try:
        project_git_prerequisite.require_git_available()
    except project_git_prerequisite.MissingGitError as exc:
        raise ProjectOnboardError(str(exc)) from exc
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=non_interactive_git_env(),
    )
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch or branch == "HEAD":
        detail = result.stderr.strip() or result.stdout.strip() or "no branch"
        raise ProjectOnboardError(
            f"could not resolve the current git branch in {cwd}: {detail}"
        )
    return branch


__all__ = [
    "REDACTED_AUTH_HEADER",
    "git_auth_header",
    "git_current_branch",
    "https_remote",
    "non_interactive_git_env",
    "remote_default_branch",
    "remote_is_reachable",
    "run_git",
]
