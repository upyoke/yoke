"""Render repository-explicit commands for session-cwd denials.

The guard never redirects or executes these commands. It teaches the caller
how to name the checkout that its work claim already authorizes. Rendering is
deliberately conservative: compound shell bodies, ambiguous multi-claim
sessions, commands that already name a repository, and local-copy ``gh``
operations receive no suggestion.
"""

from __future__ import annotations

import shlex
from pathlib import PurePath
from typing import Any, Mapping, Sequence

from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    match_read_only_signature,
)
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_payload_command,
)
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree


_GIT_TARGET_FLAGS = frozenset({"-C", "--git-dir", "--work-tree"})
_GIT_TARGET_PREFIXES = ("--git-dir=", "--work-tree=")
_GIT_CWD_INDEPENDENT = frozenset(
    {
        "clone",
        "help",
        "init",
        "version",
    }
)
_GH_REPO_FLAG_GROUPS = frozenset(
    {
        "attestation",
        "browse",
        "cache",
        "codespace",
        "issue",
        "label",
        "pr",
        "release",
        "ruleset",
        "run",
        "secret",
        "variable",
        "workflow",
    }
)
_GH_LOCAL_COPY_SHAPES = frozenset(
    {
        ("codespace", "cp"),
        ("pr", "checkout"),
        ("repo", "clone"),
        ("repo", "fork"),
    }
)


def _is_env_assignment(token: str) -> bool:
    if "=" not in token or token.startswith("-"):
        return False
    name = token.split("=", 1)[0]
    return bool(name) and name[0].isalpha() and name.replace("_", "").isalnum()


def _parse_simple_command(command: str) -> tuple[list[str], str, list[str]]:
    if not command.strip() or any(char in command for char in ";&|"):
        return [], "", []
    try:
        tokens = shlex.split(command)
    except ValueError:
        return [], "", []
    env: list[str] = []
    while tokens and _is_env_assignment(tokens[0]):
        env.append(tokens.pop(0))
    if not tokens:
        return [], "", []
    return env, tokens[0], tokens[1:]


def _has_git_target(args: Sequence[str]) -> bool:
    return any(
        arg in _GIT_TARGET_FLAGS
        or any(arg.startswith(prefix) for prefix in _GIT_TARGET_PREFIXES)
        or (arg.startswith("-C") and arg != "-C")
        for arg in args
    )


def _insert_git_checkout(
    env: Sequence[str],
    binary: str,
    args: Sequence[str],
    checkout: str,
) -> str:
    return shlex.join([*env, binary, "-C", checkout, *args])


def _render_git_command(
    command: str,
    env: list[str],
    binary: str,
    args: list[str],
    checkout: str,
) -> str:
    if _has_git_target(args) or match_read_only_signature(command):
        return ""
    if "--help" in args or "--version" in args:
        return ""
    substantive = next((arg for arg in args if not arg.startswith("-")), "")
    if not substantive or substantive in _GIT_CWD_INDEPENDENT:
        return ""
    return _insert_git_checkout(env, binary, args, checkout)


def _has_gh_repo(args: Sequence[str], env: Sequence[str]) -> bool:
    if any(value.startswith("GH_REPO=") for value in env):
        return True
    return any(
        arg in {"-R", "--repo"} or arg.startswith(("-R=", "--repo=")) for arg in args
    )


def _render_gh_command(
    env: list[str],
    binary: str,
    args: list[str],
    checkout: str,
) -> str:
    positionals = [arg for arg in args if not arg.startswith("-")]
    shape = tuple(positionals[:2])
    if not positionals or _has_gh_repo(args, env):
        return ""
    if shape in _GH_LOCAL_COPY_SHAPES or positionals[0] == "co":
        return ""
    selector = '"$(git -C ' + shlex.quote(checkout) + ' remote get-url origin)"'
    if shape == ("repo", "view"):
        prefix = shlex.join([*env, binary, "repo", "view"])
        suffix = shlex.join(args[2:])
        return f"{prefix} {selector}" + (f" {suffix}" if suffix else "")
    if positionals[0] not in _GH_REPO_FLAG_GROUPS:
        return ""
    return f"{shlex.join([*env, binary, *args])} --repo {selector}"


def render_claimed_repo_command(command: str, checkout: str) -> str:
    """Return one exact lane-bound command, or ``""`` when unsafe."""
    env, binary, args = _parse_simple_command(command)
    base = PurePath(binary).name
    if base == "git":
        return _render_git_command(command, env, binary, args, checkout)
    if base == "gh":
        return _render_gh_command(env, binary, args, checkout)
    return ""


def repo_command_block(
    payload: Mapping[str, Any],
    claims: Sequence[ClaimedWorktree],
) -> str:
    """Render the denial suffix for one unambiguous claimed lane."""
    if len(claims) != 1:
        return ""
    command = render_claimed_repo_command(
        extract_payload_command(payload),
        claims[0].worktree_path,
    )
    if not command:
        return ""
    return f"\n\nRunnable command:\n\n  {command}"


__all__ = [
    "repo_command_block",
    "render_claimed_repo_command",
]
