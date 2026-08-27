"""Every git command that reaches the network runs with the stored credential.

Yoke clones a project with the machine's stored GitHub authorization and then,
before this module existed, handed every later remote operation to whatever
credentials the surrounding shell happened to carry. On a machine onboarded
through the wizard a repo-local credential helper hid that gap; a fresh user
with no SSH key and no ``gh`` login hit it directly, and a lane publish, a
merge push, or a doctor fetch stalled until its timeout and reported nothing
anyone could act on.

This module is the one place an engine reaches a remote. It classifies the
command (:mod:`yoke_cli.config.credentialed_git_command`), decides which URL
the command will actually contact, and for the machine's configured GitHub
origin builds the same credentialed environment the clone path uses: the
stored token as a URL-scoped ``http.extraheader``, injected through
``GIT_CONFIG_*`` so it never reaches argv, ``.git/config``, or the stored
remote.

An SSH origin is contacted over HTTPS. ``url.<https>.insteadOf`` rewrites both
the scp-style and ``ssh://`` forms of the configured origin, so a checkout
cloned with an SSH remote authenticates with the stored token instead of
needing a key the user may never have created.

A command contacting anything else — another host, a file remote, a checkout
with no remote at all — runs non-interactively with no credential, because a
missing GitHub credential is not what is wrong with it. When the target *is*
the configured GitHub origin and no credential resolves, the command is
refused with the credential's name and the command that restores it, instead
of hanging on a prompt that no one is there to answer.
"""

from __future__ import annotations

import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Sequence

from yoke_cli.config.credentialed_git_command import (
    contact_url,
    is_network_command,
)

# git's own fatal exit code, so a refusal reads to callers exactly like the
# remote failure it stands in for and no call site needs a second branch.
REFUSAL_EXIT_CODE = 128
TIMEOUT_EXIT_CODE = 124

MISSING_CREDENTIAL_RECOVERY = (
    "Yoke reaches GitHub with this machine's GitHub App user authorization "
    "and nothing else stands in for it. Run `yoke github status` to see what "
    "is stored, then `yoke github connect` to authorize this machine."
)

# Refreshing a couple of minutes before expiry keeps a long merge from
# carrying a token that dies between the fetch that opened it and the push
# that ends it.
_TOKEN_REFRESH_MARGIN_SECONDS = 120

_token_lock = threading.Lock()
_cached_token: tuple[str, Any] | None = None


class CredentialedGitError(RuntimeError):
    """A remote git command has no credential for the origin it must contact."""


def run(
    args: Sequence[str],
    *,
    cwd: str | None = None,
    capture: bool = True,
    check: bool = False,
    timeout: int | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run one git command with the credential its target requires.

    Never raises for a missing credential or a timeout: both come back as a
    failed :class:`~subprocess.CompletedProcess` whose stderr names what could
    not be done and what restores it, so every existing return-code branch
    surfaces the diagnosis instead of an empty failure.
    """
    argv = ["git", *(str(item) for item in args)]
    try:
        with git_environment(args, cwd=cwd, base=env) as resolved_env:
            return _run(
                argv,
                cwd=cwd,
                capture=capture,
                check=check,
                timeout=timeout,
                env=resolved_env,
            )
    except CredentialedGitError as exc:
        if check:
            raise subprocess.CalledProcessError(
                REFUSAL_EXIT_CODE, argv, output="", stderr=str(exc),
            ) from exc
        return subprocess.CompletedProcess(
            argv, returncode=REFUSAL_EXIT_CODE, stdout="", stderr=str(exc),
        )


@contextmanager
def git_environment(
    args: Sequence[str],
    *,
    cwd: str | None = None,
    base: Mapping[str, str] | None = None,
) -> Iterator[dict[str, str]]:
    """Yield the environment ``args`` must run under.

    Local commands get a prompt-free environment and nothing else. A command
    contacting the configured GitHub origin gets the credentialed, hermetic
    one; a command contacting anything else gets the prompt-free environment
    without a credential, because no GitHub credential belongs on that wire.
    """
    from yoke_cli.config.project_git_environment import non_interactive_git_env

    if not is_network_command(args):
        yield non_interactive_git_env(base)
        return
    url = contact_url(args, cwd)
    web_url = configured_web_url()
    if not url or not is_configured_github(url, web_url):
        yield non_interactive_git_env(base)
        return
    with credentialed_github_env(url, web_url=web_url, base=base) as env:
        yield env


@contextmanager
def credentialed_github_env(
    url: str,
    *,
    web_url: str | None,
    base: Mapping[str, str] | None = None,
) -> Iterator[dict[str, str]]:
    """Yield the hermetic environment carrying the stored token for ``url``.

    Raises :class:`CredentialedGitError` when no credential resolves, naming
    the credential and its recovery, so the caller refuses in the open rather
    than falling through to an ambient one that may not exist.
    """
    from yoke_cli.config.project_git_environment import isolated_network_git_env
    from yoke_cli.config.project_git_remote_url import clean_remote_url
    from yoke_cli.config.project_git_transport import isolated_remote_config

    https_url = clean_remote_url(url, web_url=web_url)
    token = resolve_token(https_url)
    entries = (
        *isolated_remote_config(https_url, token=token, web_url=web_url),
        *_ssh_rewrite_entries(web_url),
    )
    with isolated_network_git_env(
        entries, base=base, allow_protocols="https",
    ) as env:
        yield env


def resolve_token(https_url: str) -> str:
    """Return the machine's GitHub access token, or refuse by name."""
    global _cached_token

    with _token_lock:
        cached = _cached_token
    if cached is not None and _still_valid(cached[1]):
        return cached[0]
    try:
        from yoke_cli.config import github_local_user_access

        resolved = github_local_user_access.access_token()
    except Exception as exc:  # noqa: BLE001 - every failure is one refusal
        raise CredentialedGitError(
            f"cannot authenticate a git operation against {https_url}: {exc}. "
            f"{MISSING_CREDENTIAL_RECOVERY}"
        ) from exc
    token = str(getattr(resolved, "access_token", "") or "")
    if not token:
        raise CredentialedGitError(
            f"cannot authenticate a git operation against {https_url}: the "
            "stored GitHub authorization returned no access token. "
            f"{MISSING_CREDENTIAL_RECOVERY}"
        )
    with _token_lock:
        _cached_token = (token, getattr(resolved, "expires_at", None))
    return token


def configured_web_url() -> str | None:
    """Return the machine's configured GitHub web URL, or ``None``."""
    from yoke_cli.config import machine_config

    try:
        github = machine_config.github_config(None)
    except machine_config.MachineConfigError:
        return None
    if not isinstance(github, Mapping):
        return None
    return str(github.get("web_url") or "") or None


def is_configured_github(url: str, web_url: str | None) -> bool:
    """Whether ``url`` names a repository on the configured GitHub origin."""
    from yoke_cli.config.project_git_remote_url import is_configured_github_remote

    try:
        return is_configured_github_remote(url, web_url=web_url)
    except Exception:  # noqa: BLE001 - an unreadable origin is not GitHub's
        return False


def _ssh_rewrite_entries(web_url: str | None) -> tuple[str, ...]:
    """Rewrite the configured origin's SSH forms onto its HTTPS form.

    A checkout cloned over SSH has no HTTPS remote to attach a header to. The
    rewrite is what lets the stored token serve that checkout too, instead of
    requiring a key the machine may not have.
    """
    from yoke_contracts import github_origin

    endpoint = github_origin.validate_github_web_endpoint(web_url)
    host = str(endpoint.origin).split("://", 1)[-1]
    key = f"url.{endpoint.origin}/.insteadOf"
    return (f"{key}=git@{host}:", f"{key}=ssh://git@{host}/")


def _still_valid(expires_at: Any) -> bool:
    if not isinstance(expires_at, datetime):
        return False
    deadline = expires_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    return remaining > _TOKEN_REFRESH_MARGIN_SECONDS


def _run(
    argv: list[str],
    *,
    cwd: str | None,
    capture: bool,
    check: bool,
    timeout: int | None,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess:
    kwargs: dict[str, Any] = {
        "text": True, "check": check, "env": dict(env), "timeout": timeout,
    }
    if cwd:
        kwargs["cwd"] = str(cwd)
    if capture:
        kwargs["capture_output"] = True
    else:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    try:
        return subprocess.run(argv, **kwargs)
    except subprocess.TimeoutExpired as exc:
        detail = (
            f"git {' '.join(argv[1:])} did not finish within {timeout}s. The "
            "command runs non-interactively and cannot be waiting on a "
            "prompt, so the remote is unreachable, slow, or refusing this "
            f"machine's credential. {MISSING_CREDENTIAL_RECOVERY}"
        )
        if check:
            raise subprocess.CalledProcessError(
                TIMEOUT_EXIT_CODE, argv, output=exc.output, stderr=detail,
            ) from exc
        return subprocess.CompletedProcess(
            argv,
            returncode=TIMEOUT_EXIT_CODE,
            stdout=exc.output if isinstance(exc.output, str) else "",
            stderr=detail,
        )


__all__ = [
    "CredentialedGitError",
    "MISSING_CREDENTIAL_RECOVERY",
    "REFUSAL_EXIT_CODE",
    "TIMEOUT_EXIT_CODE",
    "configured_web_url",
    "credentialed_github_env",
    "git_environment",
    "is_configured_github",
    "resolve_token",
    "run",
]
