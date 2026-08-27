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
from contextlib import contextmanager
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
            result = _run(
                argv,
                cwd=cwd,
                capture=capture,
                check=check,
                timeout=timeout,
                env=resolved_env,
            )
        if result.returncode != 0:
            result = _attributed(result, args, cwd)
        return result
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


def credential_attribution(args: Sequence[str], cwd: str | None) -> str:
    """One line naming which credential this command ran under, and why.

    A failed remote command is unattributable without it: the same git error
    appears whether Yoke supplied a credential the remote rejected or supplied
    none at all, and those need opposite responses. Recomputed only on
    failure, so the successful path pays nothing for it.
    """
    if not is_network_command(args):
        return ""
    url = contact_url(args, cwd)
    if not url:
        return (
            "No credential was applied: the remote this command would contact "
            "could not be resolved from the checkout, so there was nothing to "
            "authenticate against."
        )
    web_url = configured_web_url()
    if not is_configured_github(url, web_url):
        return (
            f"No credential was applied: {url} is not this machine's "
            f"configured GitHub origin ({web_url or 'https://github.com'}), so "
            "the command ran with the ambient credentials for that remote."
        )
    return (
        f"This machine's stored GitHub credential WAS applied, scoped to "
        f"{url}. A credential prompt or authentication failure above means "
        "the remote rejected it rather than that none was supplied — check "
        "`yoke github status`, and reconnect with `yoke github connect` if it "
        "reports anything other than ready."
    )


def _attributed(
    result: subprocess.CompletedProcess,
    args: Sequence[str],
    cwd: str | None,
) -> subprocess.CompletedProcess:
    """Append the credential attribution to a failed command's stderr."""
    attribution = credential_attribution(args, cwd)
    if not attribution:
        return result
    stderr = (result.stderr or "").rstrip()
    joined = f"{stderr}\n{attribution}" if stderr else attribution
    return subprocess.CompletedProcess(
        result.args, result.returncode, result.stdout, joined,
    )


def resolve_token(https_url: str) -> str:
    """Return the machine's GitHub token for a git request, or refuse by name.

    Resolution goes through the same credential store the installed git
    credential helper reads. That store holds the machine operation lock and
    hands back the credential that is current *now*. The caller has already
    established that the target is the configured GitHub origin, so the
    store's own host match would only repeat that decision.

    The API-side reader is deliberately not used here. Refreshing a GitHub App
    user authorization rotates it and revokes the previous access token, so a
    git command that minted its own token through that path could have it
    revoked out from under it by any other Yoke process on the machine that
    refreshed in between — which is a push that fails with a credential prompt
    on a busy machine and succeeds on a quiet one.
    """
    from yoke_cli.config import github_git_credential_store as store
    from yoke_cli.config import github_merge_path_binding
    from yoke_cli.config import machine_config

    # Which Yoke connection the machine profile is proven against is pinned
    # the same way a merge child pins it: an owner-only admin connection is a
    # door into one universe's database, not a plane that can answer for the
    # saved profile, so the https sibling it administers answers instead.
    # Without this a merge refuses at the moment it tries to publish, by
    # which point its engine has already switched to the admin connection.
    selection = github_merge_path_binding.resolve_selection()
    try:
        credential = store.access_token_from_machine_config(
            machine_config.config_path(None),
            expected_service_api_url=selection.service_api_url,
            expected_local_connection=selection.local_connection_selected,
        )
    except Exception as exc:  # noqa: BLE001 - every failure is one refusal
        raise CredentialedGitError(
            f"cannot authenticate a git operation against {https_url}: {exc}. "
            f"{MISSING_CREDENTIAL_RECOVERY}"
        ) from exc
    token = str((credential or {}).get("access_token") or "")
    if not token:
        raise CredentialedGitError(
            f"cannot authenticate a git operation against {https_url}: the "
            "stored GitHub authorization returned no access token. "
            f"{MISSING_CREDENTIAL_RECOVERY}"
        )
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
        partial = exc.stderr if isinstance(exc.stderr, str) else ""
        detail = (
            f"git {' '.join(argv[1:])} did not finish within {timeout}s. The "
            "command runs non-interactively and cannot be waiting on a "
            "prompt, so the remote is unreachable, slow, or refusing this "
            f"machine's credential. {MISSING_CREDENTIAL_RECOVERY}"
        )
        # Whatever the command managed to say before the deadline is often the
        # only clue about where it stalled; a timeout must not discard it.
        detail = f"{partial.rstrip()}\n{detail}" if partial.strip() else detail
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
