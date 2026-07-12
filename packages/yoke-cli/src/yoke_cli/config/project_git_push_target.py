"""Fail-closed validation of the effective target for authenticated Git pushes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from yoke_cli.config.project_git_environment import isolated_network_git_env
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_cli.config.project_git_process import (
    NetworkGitBoundaryError,
    run_network_git,
)


_REMOTE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_REWRITE_KEY = re.compile(
    r"^url\.(?P<replacement>.+)\.(?P<kind>insteadof|pushinsteadof)$",
    re.IGNORECASE,
)
_TRACE_TARGET_KEY = re.compile(
    r"^trace2\.(?:eventtarget|normaltarget|perftarget|configparams|envvars)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PushTarget:
    remote: str
    selected_url: str
    effective_urls: tuple[str, ...]


def effective_push_urls(cwd: Path, args: tuple[str, ...]) -> PushTarget:
    """Resolve every effective push URL after rejecting local rewrite targets."""

    remote = _push_remote(args)
    if remote is None or not _REMOTE_NAME.fullmatch(remote):
        raise ProjectOnboardError(
            "GitHub push authorization could not resolve the target remote"
        )
    selected_urls = _config_values(cwd, f"remote.{remote}.url")
    if not selected_urls:
        raise ProjectOnboardError(
            "GitHub push authorization could not resolve the target remote"
        )
    push_urls = _config_values(cwd, f"remote.{remote}.pushurl")
    _reject_local_routing(cwd, (*selected_urls, *push_urls))
    result = _run(
        cwd, "remote", "get-url", "--push", "--all", remote,
    )
    urls = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    if result.returncode != 0 or not urls:
        raise ProjectOnboardError(
            "GitHub push authorization could not resolve the effective push URL"
        )
    return PushTarget(
        remote=remote, selected_url=selected_urls[0], effective_urls=urls,
    )


def reject_local_push_policy(cwd: Path, url: str, *, remote: str) -> None:
    """Reject repo-local policy applicable to the canonical HTTPS target."""

    _reject_local_routing(cwd, (url,))
    signing = _run(
        cwd, "config", "--includes", "--get-regexp",
        r"^gpg\..*program$",
    )
    if signing.returncode not in (0, 1):
        raise ProjectOnboardError(
            "GitHub push authorization could not inspect signing programs"
        )
    if signing.stdout.strip():
        raise ProjectOnboardError(
            "repository-local Git signing programs must be removed before "
            "GitHub push"
        )
    resolved = _run(cwd, "ls-remote", "--get-url", url)
    resolved_url = resolved.stdout.strip()
    if resolved.returncode != 0 or resolved_url != url:
        raise ProjectOnboardError(
            "repository-local Git URL rewriting must be removed before GitHub push"
        )
    matched = _run(cwd, "config", "--includes", "--get-urlmatch", "http", url)
    if matched.returncode not in (0, 1):
        raise ProjectOnboardError(
            "GitHub push authorization could not inspect repository HTTP policy"
        )
    if matched.stdout.strip():
        raise ProjectOnboardError(
            "repository-local Git HTTP overrides must be removed before GitHub push"
        )
    routing = {
        key: _config_values(cwd, f"remote.{remote}.{key}")
        for key in ("proxy", "vcs", "receivepack", "uploadpack")
    }
    if any(
        value.strip() for values in routing.values() for value in values
    ):
        raise ProjectOnboardError(
            "repository-local Git transport overrides must be removed before "
            "GitHub push"
        )


def _reject_local_routing(cwd: Path, urls: tuple[str, ...]) -> None:
    result = _run(cwd, "config", "--includes", "--get-regexp", r"^(url\.|trace2\.)")
    if result.returncode not in (0, 1):
        raise ProjectOnboardError(
            "GitHub push authorization could not inspect repository routing"
        )
    for line in result.stdout.splitlines():
        key, separator, value = line.partition(" ")
        if not separator:
            continue
        if _TRACE_TARGET_KEY.fullmatch(key) and value.strip():
            raise ProjectOnboardError(
                "repository-local Git tracing must be disabled before GitHub push"
            )
        match = _REWRITE_KEY.fullmatch(key)
        prefix = value.strip()
        if match and prefix and any(url.startswith(prefix) for url in urls):
            raise ProjectOnboardError(
                "repository-local Git URL rewriting must be removed before GitHub push"
            )


def _config_values(cwd: Path, key: str) -> tuple[str, ...]:
    result = _run(cwd, "config", "--get-all", key)
    if result.returncode not in (0, 1):
        raise ProjectOnboardError(
            "GitHub push authorization could not inspect the target remote"
        )
    return tuple(line for line in result.stdout.splitlines() if line)


def _run(cwd: Path, *args: str):
    try:
        with isolated_network_git_env(()) as env:
            return run_network_git(
                ["git", *args], cwd=cwd, env=env,
                timeout_seconds=10, maximum_output_bytes=1024 * 1024,
            )
    except (OSError, NetworkGitBoundaryError) as exc:
        raise ProjectOnboardError(
            "GitHub push target inspection exceeded its safety boundary"
        ) from exc


def _push_remote(args: tuple[str, ...]) -> str | None:
    if not args or args[0] != "push":
        return None
    return next((item for item in args[1:] if not item.startswith("-")), None)


__all__ = [
    "PushTarget",
    "effective_push_urls",
    "reject_local_push_policy",
]
