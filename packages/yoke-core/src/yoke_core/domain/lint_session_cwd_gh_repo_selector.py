"""Recognize lane-bound repository selectors in GitHub CLI commands."""

from __future__ import annotations

import re
import shlex
from pathlib import PurePath
from typing import List


_REMOTE_SELECTOR_RE = re.compile(
    r"\$\(\s*git\s+-C\s+(?P<path>'[^']*'|\"[^\"]*\"|[^\s)]+)"
    r"\s+remote\s+get-url\s+origin\s*\)"
)
_SHELL_CONTROL = frozenset(";&|`")


def _is_env_assignment(token: str) -> bool:
    if "=" not in token or token.startswith("-"):
        return False
    name = token.split("=", 1)[0]
    return bool(name) and name[0].isalpha() and name.replace("_", "").isalnum()


def extract_gh_repo_selector_targets(command: str) -> List[str]:
    """Return the checkout in one exact ``gh --repo $(git -C ...)`` shape."""
    if command.count("$(") != 1 or any(char in command for char in _SHELL_CONTROL):
        return []
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    while tokens and _is_env_assignment(tokens[0]):
        tokens.pop(0)
    if not tokens or PurePath(tokens[0]).name != "gh":
        return []

    selectors: List[str] = []
    for index, token in enumerate(tokens):
        if token == "--repo" and index + 1 < len(tokens):
            selectors.append(tokens[index + 1])
        elif token.startswith("--repo="):
            selectors.append(token.split("=", 1)[1])
    if len(selectors) != 1:
        return []

    match = _REMOTE_SELECTOR_RE.fullmatch(selectors[0])
    if match is None:
        return []
    try:
        paths = shlex.split(match.group("path"))
    except ValueError:
        return []
    return paths if len(paths) == 1 and PurePath(paths[0]).is_absolute() else []


__all__ = ["extract_gh_repo_selector_targets"]
