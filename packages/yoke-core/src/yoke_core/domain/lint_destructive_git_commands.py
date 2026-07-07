"""Command parsing helpers for the destructive-git hook."""

from __future__ import annotations

import re
import shlex
from typing import Tuple

_SEP_RE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def parse_git_invocations(command: str) -> list[Tuple[list[str], str]]:
    out: list[Tuple[list[str], str]] = []
    for stmt in _SEP_RE.split(command or ""):
        if not stmt.strip():
            continue
        try:
            tokens = shlex.split(stmt, posix=True)
        except ValueError:
            continue
        i = 0
        while i < len(tokens) and _ENV_RE.match(tokens[i]):
            i += 1
        if i >= len(tokens) or tokens[i].rsplit("/", 1)[-1] != "git":
            continue
        i += 1
        repo_path = ""
        while i < len(tokens):
            t = tokens[i]
            if t == "-C" and i + 1 < len(tokens):
                repo_path = tokens[i + 1]
                i += 2
            elif t.startswith("-C") and len(t) > 2:
                repo_path = t[2:]
                i += 1
            elif t == "-c" and i + 1 < len(tokens):
                i += 2
            elif t.startswith("-"):
                i += 1
            else:
                break
        if i < len(tokens):
            out.append((tokens[i:], repo_path))
    return out
