"""What one git command is, before anything decides how to authorize it.

Engine call sites routinely lead with ``-C <path>``, so a command's
subcommand is never reliably its first argument; classifying on that position
is how a push behind ``-C`` reads as a local command and quietly skips its
credential. Reading argv is a separate concern from resolving authority, and
keeping it here means the authority layer can be exercised against a command
shape without a checkout, and the shapes without a token.
"""

from __future__ import annotations

import subprocess
from typing import Sequence

NETWORK_SUBCOMMANDS = frozenset({"clone", "fetch", "ls-remote", "pull", "push"})
NETWORK_REMOTE_ACTIONS = frozenset({"update", "prune"})
_GLOBAL_OPTIONS_WITH_VALUE = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
    "--config-env",
})


def split_git_args(args: Sequence[str]) -> tuple[list[str], str, list[str]]:
    """Split ``args`` into git's global options, its subcommand, and the rest."""
    argv = [str(item) for item in args]
    if argv and argv[0] == "git":
        argv = argv[1:]
    index = 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith("-"):
            return argv[:index], token, argv[index + 1:]
        if token in _GLOBAL_OPTIONS_WITH_VALUE:
            index += 2
            continue
        index += 1
    return argv, "", []


def is_network_command(args: Sequence[str]) -> bool:
    """Whether running ``args`` will contact a remote."""
    _, subcommand, rest = split_git_args(args)
    if subcommand in NETWORK_SUBCOMMANDS:
        return True
    if subcommand != "remote":
        return False
    return any(item in NETWORK_REMOTE_ACTIONS for item in rest)


def command_cwd(args: Sequence[str], cwd: str | None) -> str | None:
    """Return the directory the command runs against, honoring ``-C``."""
    globals_, _, _ = split_git_args(args)
    for index, token in enumerate(globals_):
        if token == "-C" and index + 1 < len(globals_):
            return globals_[index + 1]
    return cwd


def contact_url(args: Sequence[str], cwd: str | None) -> str:
    """Return the remote URL the command will contact, or ``""``.

    A named remote is resolved against the checkout, a URL operand is taken as
    written, and an omitted operand means ``origin`` — the default git itself
    applies for every network subcommand engines run.
    """
    _, subcommand, rest = split_git_args(args)
    operand = _first_operand(rest)
    if subcommand == "clone":
        return operand
    repo = command_cwd(args, cwd)
    if operand and ("://" in operand or "@" in operand or "/" in operand):
        return operand
    return remote_url(repo, operand or "origin")


def remote_url(repo: str | None, remote: str) -> str:
    """Return the configured URL of ``remote``, or ``""`` when it has none."""
    argv = ["git"]
    if repo:
        argv += ["-C", str(repo)]
    argv += ["remote", "get-url", remote]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _first_operand(rest: Sequence[str]) -> str:
    for token in rest:
        if not token.startswith("-"):
            return token
    return ""


__all__ = [
    "NETWORK_REMOTE_ACTIONS",
    "NETWORK_SUBCOMMANDS",
    "command_cwd",
    "contact_url",
    "is_network_command",
    "remote_url",
    "split_git_args",
]
