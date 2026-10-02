"""Prefer isolated Yoke authorization; absent authorization permits bounded,
non-interactive Git with the user's own credentials. GitHub API authority stays
independent, and failed stored authorization never falls back.
"""

from __future__ import annotations

import subprocess
from contextlib import ExitStack, contextmanager
from typing import Any, Iterator, Mapping, Sequence

from yoke_cli.config import credentialed_git_attribution as attribution
from yoke_cli.config.credentialed_git_command import (
    contact_url,
    is_network_command,
)
from yoke_contracts.github_auth_transience import GITHUB_AUTH_RETRY_RECIPE

# Return refusals in Git's existing failed-command shape.
REFUSAL_EXIT_CODE = 128
TIMEOUT_EXIT_CODE = 124

RECONNECT_RECOVERY = (
    "Yoke reaches GitHub with this machine's GitHub App user authorization "
    "and nothing else stands in for it. Run `yoke github status` to see what "
    "is stored, then `yoke github connect` to authorize this machine."
)
# Reconnect only for permanent failure: it revokes other in-flight tokens.
TRANSIENT_RECOVERY = (
    "The stored authorization still stands: this read collided with another "
    "local GitHub operation or could not reach GitHub, so "
    f"{GITHUB_AUTH_RETRY_RECIPE}. Do not reconnect GitHub to clear it — a "
    "reconnect rotates the authorization and revokes the token every other "
    "running command is carrying."
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
    """Run Git with its selected credential; failures name their recovery."""
    argv = ["git", *(str(item) for item in args)]
    try:
        with _decided_environment(args, cwd=cwd, base=env) as (
            resolved_env,
            decision,
        ):
            if decision.own_credentials:
                result = _run_own_credentials(argv, cwd, resolved_env, timeout)
            else:
                result = _run(
                    argv,
                    cwd=cwd,
                    capture=capture,
                    check=check,
                    timeout=timeout,
                    env=resolved_env,
                )
        if result.returncode != 0:
            result = attribution.attributed(result, decision)
        result.credential_source = (
            "pushed with Yoke GitHub access"
            if decision.token_applied
            else "pushed with your own git credentials"
            if decision.own_credentials
            else ""
        )
        if check and result.returncode:
            raise subprocess.CalledProcessError(
                result.returncode, argv, output=result.stdout, stderr=result.stderr
            )
        return result
    except CredentialedGitError as exc:
        if check:
            raise subprocess.CalledProcessError(
                REFUSAL_EXIT_CODE,
                argv,
                output="",
                stderr=str(exc),
            ) from exc
        return subprocess.CompletedProcess(argv, REFUSAL_EXIT_CODE, "", str(exc))


@contextmanager
def git_environment(
    args: Sequence[str],
    *,
    cwd: str | None = None,
    base: Mapping[str, str] | None = None,
) -> Iterator[dict[str, str]]:
    """Yield the environment ``args`` must run under."""

    with _decided_environment(args, cwd=cwd, base=base) as (env, _decision):
        yield env


@contextmanager
def _decided_environment(
    args: Sequence[str],
    *,
    cwd: str | None,
    base: Mapping[str, str] | None,
) -> Iterator[tuple[dict[str, str], attribution.CredentialDecision]]:
    """Carry the credential decision alongside its environment."""
    from yoke_cli.config.project_git_environment import non_interactive_git_env

    if not is_network_command(args):
        yield non_interactive_git_env(base), attribution.LOCAL_COMMAND
        return
    url = contact_url(args, cwd)
    web_url = configured_web_url()
    if not url or not is_configured_github(url, web_url):
        yield (
            non_interactive_git_env(base),
            attribution.CredentialDecision(
                network=True, url=url or "", web_url=web_url
            ),
        )
        return
    with ExitStack() as stack:
        try:
            env = stack.enter_context(
                credentialed_github_env(url, web_url=web_url, base=base)
            )
        except CredentialedGitError:
            from yoke_cli.config import machine_config
            from yoke_cli.config.project_git_environment import git_config_env

            try:
                github = machine_config.github_config(None)
            except machine_config.MachineConfigError as exc:
                raise CredentialedGitError(str(exc)) from exc
            if github.get("authorization") is not None:
                raise
            yield (
                git_config_env(
                    ("credential.interactive=false", "core.askPass="),
                    base=base,
                ),
                attribution.CredentialDecision(
                    network=True,
                    url=url,
                    web_url=web_url,
                    own_credentials=True,
                ),
            )
            return
        yield (
            env,
            attribution.CredentialDecision(
                network=True,
                url=url,
                web_url=web_url,
                token_applied=True,
            ),
        )


@contextmanager
def credentialed_github_env(
    url: str,
    *,
    web_url: str | None,
    base: Mapping[str, str] | None = None,
) -> Iterator[dict[str, str]]:
    """Yield the isolated stored-token environment or refuse with recovery."""
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
        entries,
        base=base,
        allow_protocols="https",
    ) as env:
        yield env


def resolve_token(https_url: str) -> str:
    """Read the shared cached token, retrying transient failures."""
    from yoke_cli.config import github_git_credential_store as store
    from yoke_cli.config import github_local_user_access
    from yoke_cli.config import github_merge_path_binding
    from yoke_cli.config import machine_config
    from yoke_contracts.github_auth_transience import call_with_transient_retry

    # Prove the profile through the HTTPS sibling, even under an admin connection.
    selection = github_merge_path_binding.resolve_selection()
    try:
        credential = call_with_transient_retry(
            lambda: store.access_token_from_machine_config(
                machine_config.config_path(None),
                expected_service_api_url=selection.service_api_url,
                expected_local_connection=selection.local_connection_selected,
            ),
            is_transient=github_local_user_access.is_transient_access_failure,
        )
    except Exception as exc:  # noqa: BLE001 - every failure is one refusal
        recovery = (
            TRANSIENT_RECOVERY
            if github_local_user_access.is_transient_access_failure(exc)
            else RECONNECT_RECOVERY
        )
        raise CredentialedGitError(
            f"cannot authenticate a git operation against {https_url}: {exc}. "
            f"{recovery}"
        ) from exc
    token = str((credential or {}).get("access_token") or "")
    if not token:
        raise CredentialedGitError(
            f"cannot authenticate a git operation against {https_url}: the "
            "stored GitHub authorization returned no access token. "
            f"{RECONNECT_RECOVERY}"
        )
    return token


def _run_own_credentials(argv, cwd, env, timeout):
    """Bound the optional child and its helpers as one process group."""
    from pathlib import Path
    from yoke_cli.config import project_git_process, repo_upstream_git

    deadline = (
        timeout if timeout is not None else repo_upstream_git.network_timeout_seconds()
    )
    try:
        result = project_git_process.run_network_git(
            argv,
            cwd=Path(cwd) if cwd else None,
            env=env,
            timeout_seconds=deadline,
        )
        return subprocess.CompletedProcess(
            argv, result.returncode, result.stdout, result.stderr
        )
    except project_git_process.NetworkGitBoundaryError as exc:
        return subprocess.CompletedProcess(argv, TIMEOUT_EXIT_CODE, "", str(exc))


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
    """Rewrite SSH origins to HTTPS so the stored header applies."""
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
        "text": True,
        "check": check,
        "env": dict(env),
        "timeout": timeout,
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
            f"machine's credential. {TRANSIENT_RECOVERY}"
        )
        # Preserve the child's evidence of where it stalled.
        detail = f"{partial.rstrip()}\n{detail}" if partial.strip() else detail
        if check:
            raise subprocess.CalledProcessError(
                TIMEOUT_EXIT_CODE,
                argv,
                output=exc.output,
                stderr=detail,
            ) from exc
        output = exc.output if isinstance(exc.output, str) else ""
        return subprocess.CompletedProcess(argv, TIMEOUT_EXIT_CODE, output, detail)


__all__ = [
    "CredentialedGitError",
    "RECONNECT_RECOVERY",
    "TRANSIENT_RECOVERY",
    "REFUSAL_EXIT_CODE",
    "TIMEOUT_EXIT_CODE",
    "configured_web_url",
    "credentialed_github_env",
    "git_environment",
    "is_configured_github",
    "resolve_token",
    "run",
]
