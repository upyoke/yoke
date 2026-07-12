"""Non-interactive HTTPS git transport for project onboarding.

Onboarding runs every project git operation over HTTPS, never SSH: the Textual
wizard owns the TTY, so an SSH host-key prompt on a fresh host (no ``known_hosts``)
would garble the UI, swallow the user's "yes", and deadlock onboarding. This
module is the single home for that transport policy:

* :func:`https_remote` builds the clean HTTPS ``origin`` URL — no embedded
  credential.
* :func:`git_auth_header` encodes the connected token as a URL-scoped HTTP
  Basic header (``x-access-token:<TOKEN>``) — the single source of the encoding
  shared by the clone-side and push-side runners.
* :func:`non_interactive_git_env` builds a git subprocess env that can never
  block on a prompt (``GIT_TERMINAL_PROMPT=0`` plus a ``BatchMode``/``accept-new``
  ``GIT_SSH_COMMAND`` for any residual SSH path).
* :func:`run_git` injects ephemeral config through ``GIT_CONFIG_*`` environment
  keys, never process argv, ``.git/config``, or the stored remote.
"""

from __future__ import annotations

import base64
from pathlib import Path
import urllib.parse

from yoke_contracts import github_origin
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_cli.config.project_git_environment import (
    git_config_env,
    isolated_network_git_env,
    non_interactive_git_env,
)
from yoke_cli.config.project_git_diagnostics import scrub_git_diagnostic
from yoke_cli.config.project_git_process import (
    NetworkGitBoundaryError,
    run_network_git,
)
from yoke_cli.config.project_git_remote_url import (
    clean_remote_url,
    is_configured_github_remote,
)
from yoke_cli.config.project_git_push_target import (
    effective_push_urls,
    reject_local_push_policy,
)
from yoke_cli.config import project_git_probe
from yoke_cli.config import project_git_upstream
from yoke_cli.config import project_local_git

# The redaction placeholder substituted for the auth header in any surfaced
# error so a token can never reach a log line.
REDACTED_AUTH_HEADER = "AUTHORIZATION: basic [redacted]"
GENERAL_CREDENTIAL_HELPER_KEY = "credential.helper"
GENERAL_HTTP_EXTRA_HEADER_KEY = "http.extraHeader"
REMOTE_FAILURE_ACCESS = project_git_probe.FAILURE_ACCESS


def https_remote(github_repo: str, *, web_url: str | None = None) -> str:
    """Return the clean HTTPS remote URL for ``owner/repo``.

    The returned URL is the stored ``origin`` — clean, with no embedded
    credential; the connected token travels separately as a URL-scoped
    ``http.extraheader`` (see :func:`git_auth_header`). HTTPS is used because the
    wizard owns the TTY and an SSH host-key prompt would deadlock onboarding.
    """
    endpoint = github_origin.validate_github_web_endpoint(web_url)
    repo = github_origin.normalize_github_repository(
        github_repo, web_url=endpoint.base_url,
    )
    return endpoint.url(f"/{repo}.git")


def git_auth_header(token: str) -> str:
    """Build the ``http.extraheader`` value carrying the token as HTTP Basic.

    GitHub accepts ``x-access-token:<TOKEN>`` base64-encoded as Basic auth. The
    value is consumed through ephemeral ``GIT_CONFIG_*`` subprocess variables
    and never persisted to ``.git/config`` or the stored remote. Single source of
    the encoding so the clone-side runner and the push-side runner agree.
    """
    encoded = base64.b64encode(
        f"x-access-token:{token}".encode("utf-8")
    ).decode("ascii")
    return f"AUTHORIZATION: basic {encoded}"


def git_auth_config(
    token: str,
    url: str,
    *,
    web_url: str | None = None,
) -> str | None:
    """Return auth scoped only to the validated configured GitHub origin."""
    endpoint = github_origin.validate_github_web_endpoint(web_url)
    try:
        github_origin.normalize_github_repository(url, web_url=endpoint.base_url)
    except github_origin.GitHubApiOriginError:
        return None
    return f"http.{endpoint.origin}/.extraheader={git_auth_header(token)}"


def isolated_remote_config(
    url: str,
    *,
    token: str | None = None,
    web_url: str | None = None,
) -> tuple[str, ...]:
    """Reset ambient auth for one remote, optionally adding one Yoke header."""

    endpoint = github_origin.validate_github_web_endpoint(web_url)
    clean_url = clean_remote_url(url, web_url=endpoint.base_url)
    remote = urllib.parse.urlsplit(clean_url)
    remote_origin = urllib.parse.urlunsplit(
        (remote.scheme, remote.netloc, "", "", "")
    )
    if token and not is_configured_github_remote(
        clean_url, web_url=endpoint.base_url,
    ):
        raise ProjectOnboardError(
            "GitHub App authorization cannot be sent to a repository outside "
            "the configured GitHub origin"
        )
    isolated_origins = tuple(dict.fromkeys((endpoint.origin, remote_origin)))
    entries = (
        f"{GENERAL_CREDENTIAL_HELPER_KEY}=",
        *(f"credential.{origin}.helper=" for origin in isolated_origins),
        f"{GENERAL_HTTP_EXTRA_HEADER_KEY}=",
        *(f"http.{origin}/.extraheader=" for origin in isolated_origins),
        f"http.{clean_url}.extraheader=",
        "core.askPass=",
        "credential.interactive=false",
        "http.followRedirects=false",
        "http.proxy=",
        "http.sslVerify=true",
        "http.cookieFile=",
        "http.saveCookies=false",
        "push.gpgSign=false",
        "push.recurseSubmodules=no",
        f"http.{clean_url}.sslVerify=true",
        f"http.{clean_url}.followRedirects=false",
        f"http.{clean_url}.proxy=",
        f"http.{clean_url}.cookieFile=",
        f"http.{clean_url}.saveCookies=false",
    )
    if token:
        entries = (
            *entries,
            f"http.{clean_url}.extraheader={git_auth_header(token)}",
        )
    return entries


def run_git(
    cwd: Path,
    *args: str,
    token: str | None = None,
    github_web_url: str | None = None,
) -> None:
    """Run a git command non-interactively, optionally with the ephemeral token.

    Always runs under :func:`non_interactive_git_env` so no git op can hang on a
    credential or host-key prompt while the wizard owns the terminal. When
    ``token`` is given, its header is injected through ``GIT_CONFIG_*``
    subprocess variables, so neither the token nor encoded header appears in
    process argv, ``.git/config``, or the stored remote.
    """
    try:
        project_git_prerequisite.require_git_available()
    except project_git_prerequisite.MissingGitError as exc:
        raise ProjectOnboardError(str(exc)) from exc
    entries: tuple[str, ...] = ()
    run_args = args
    upstream: tuple[str, str] | None = None
    upstream_snapshot: project_git_upstream.UpstreamSnapshot | None = None
    if token:
        target = effective_push_urls(cwd, args)
        remote_url = clean_remote_url(
            target.selected_url, web_url=github_web_url,
        )
        effective = tuple(
            clean_remote_url(url, web_url=github_web_url)
            for url in target.effective_urls
        )
        if len(effective) != 1 or any(
            url.casefold() != remote_url.casefold() for url in effective
        ):
            raise ProjectOnboardError(
                "GitHub push target does not match the selected origin repository"
            )
        # URL-matched http.* policy must be inspected against the URL Git will
        # actually contact.  Raw SSH/scp remotes do not participate in Git's
        # HTTP URL matching and inspecting them would miss hostile CA, proxy,
        # resolve, cookie, or redirect policy for this canonical HTTPS target.
        reject_local_push_policy(
            cwd, remote_url, remote=target.remote,
        )
        entries = (
            *isolated_remote_config(
                remote_url, token=token, web_url=github_web_url,
            ),
            f"remote.{target.remote}.proxy=",
        )
        run_args, upstream = _direct_push_args(
            args, remote=target.remote, url=remote_url,
        )
        if upstream is not None:
            upstream_snapshot = project_git_upstream.configure(
                cwd, remote=upstream[0], branch=upstream[1],
            )
    try:
        if _network_command(run_args):
            with isolated_network_git_env(
                entries, allow_protocols="https" if token else None,
            ) as env:
                result = run_network_git(["git", *run_args], cwd=cwd, env=env)
        else:
            result = run_network_git(
                ["git", *args], cwd=cwd, env=git_config_env(entries),
                timeout_seconds=60,
            )
    except NetworkGitBoundaryError as exc:
        if upstream_snapshot is not None:
            project_git_upstream.restore(cwd, upstream_snapshot)
        raise ProjectOnboardError(
            scrub_git_diagnostic(exc, token=token)
        ) from exc
    if result.returncode != 0:
        if upstream_snapshot is not None:
            project_git_upstream.restore(cwd, upstream_snapshot)
        detail = result.stderr.strip() or result.stdout.strip()
        detail = scrub_git_diagnostic(detail, token=token)
        raise ProjectOnboardError(
            f"git {' '.join(args)} failed with {result.returncode}: {detail}"
        )


def remote_default_branch(
    url: str,
    token: str | None = None,
    *,
    github_web_url: str | None = None,
) -> str | None:
    """Return the default branch of the remote ``url`` without cloning it.

    Runs ``git ls-remote --symref <url> HEAD`` non-interactively and parses the
    symref line (``ref: refs/heads/<branch>\\tHEAD``) so a clone of a ``master``
    (or any non-``main``) source records the source's real default branch instead
    of a hardcoded guess. ``token`` is injected as the same URL-scoped
    ``http.extraheader`` :func:`run_git` uses, so a private source is reachable
    without an interactive prompt. Returns ``None`` on any failure (network down,
    auth refused, unparseable output, no symref line) so the wizard can fall back
    to a plain default rather than crash on a probe.
    """
    return remote_probe(
        url, token=token, github_web_url=github_web_url,
    ).default_branch


def remote_is_reachable(
    url: str,
    token: str | None = None,
    *,
    github_web_url: str | None = None,
) -> bool:
    """True when the remote ``url`` answers a metadata probe with the given auth.

    A thin wrapper over the same ``ls-remote`` probe :func:`remote_default_branch`
    runs: it confirms the repo exists and the credentials (ambient or ``token``)
    can read it, so the wizard can reject an unreachable URL inline instead of
    deferring the failure to a clone at apply. Returns ``False`` on any failure.
    """
    return remote_probe(
        url, token=token, github_web_url=github_web_url,
    ).reachable


def remote_probe(
    url: str,
    token: str | None = None,
    *,
    github_web_url: str | None = None,
) -> project_git_probe.GitRemoteProbe:
    """Return structured auth/network provenance from one bounded probe."""

    if not str(url or "").strip():
        return project_git_probe.GitRemoteProbe(
            False, failure_kind=project_git_probe.FAILURE_OTHER,
        )
    try:
        cleaned = clean_remote_url(url, web_url=github_web_url)
        entries = isolated_remote_config(
            cleaned, token=token, web_url=github_web_url,
        )
    except ProjectOnboardError:
        return project_git_probe.GitRemoteProbe(
            False, failure_kind=project_git_probe.FAILURE_OTHER,
        )
    project_git_prerequisite.require_git_available()
    return project_git_probe.probe_remote(
        cleaned, entries, runner=run_network_git,
    )


git_current_branch = project_local_git.current_branch


def _network_command(args: tuple[str, ...]) -> bool:
    return bool(args) and args[0] in {"clone", "fetch", "ls-remote", "pull", "push"}


def _direct_push_args(
    args: tuple[str, ...], *, remote: str, url: str,
) -> tuple[tuple[str, ...], tuple[str, str] | None]:
    direct: list[str] = []
    upstream_requested = False
    replaced = False
    for item in args:
        if item in ("-u", "--set-upstream"):
            upstream_requested = True
            continue
        if not replaced and item == remote:
            direct.append(url)
            replaced = True
            continue
        direct.append(item)
    branch = direct[-1] if len(direct) > 2 else ""
    upstream = (remote, branch) if upstream_requested and branch else None
    return tuple(direct), upstream


__all__ = [
    "REDACTED_AUTH_HEADER",
    "REMOTE_FAILURE_ACCESS",
    "GENERAL_CREDENTIAL_HELPER_KEY",
    "GENERAL_HTTP_EXTRA_HEADER_KEY",
    "clean_remote_url",
    "git_auth_header",
    "git_auth_config",
    "git_current_branch",
    "git_config_env",
    "https_remote",
    "is_configured_github_remote",
    "isolated_remote_config",
    "non_interactive_git_env",
    "remote_default_branch",
    "remote_is_reachable",
    "remote_probe",
    "run_git",
]
