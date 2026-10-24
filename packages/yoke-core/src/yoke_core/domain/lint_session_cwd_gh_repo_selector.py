"""Recognize lane-bound repository selectors in GitHub CLI commands."""

from __future__ import annotations

import re
import shlex
from pathlib import PurePath
from typing import List

from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell

_REMOTE_SELECTOR_RE = re.compile(
    r"\$\(\s*git\s+-C\s+(?P<path>'[^']*'|\"[^\"]*\"|[^\s)]+)"
    r"\s+remote\s+get-url\s+origin\s*\)"
)
_SHELL_CONTROL = frozenset(";&|`")


def extract_gh_repo_selector_targets(command: str | ShellParse) -> List[str]:
    """Return the checkout in one exact ``gh --repo $(git -C ...)`` shape.

    The control-character check reads the raw text on purpose: a ``;``
    or backtick inside the quoted ``$(...)`` selector still runs.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    code = parsed.code
    if code.count("$(") != 1 or any(char in code for char in _SHELL_CONTROL):
        return []
    if parsed.unparsed or len(parsed.segments) != 1:
        return []
    tokens = parsed.segments[0].argv
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
