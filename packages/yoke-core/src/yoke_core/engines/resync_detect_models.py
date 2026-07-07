"""Data structures and normalization for resync detection."""

from __future__ import annotations

from typing import Any, Dict, List

class PairedItem:
    """Represents a local item/task paired with a GitHub issue."""

    __slots__ = ("id", "file", "gh_num", "type", "project", "repo")

    def __init__(
        self,
        id: str,
        file: str,
        gh_num: int,
        type: str,
        project: str,
        repo: str,
    ):
        self.id = id
        self.file = file
        self.gh_num = gh_num
        self.type = type
        self.project = project
        self.repo = repo


class DriftRecord:
    """A single field drift between local and GitHub."""

    __slots__ = ("id", "field", "local", "github")

    def __init__(self, id: str, field: str, local: str, github: str):
        self.id = id
        self.field = field
        self.local = local
        self.github = github

    def to_pipe(self) -> str:
        return f"{self.id}|{self.field}|{self.local}|{self.github}"


def _trim_trailing(text: str) -> str:
    if not text:
        return ""
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def normalize_body_for_compare(text: str) -> str:
    """Normalize body text for comparison.

    Accounts for GitHub API escape interpretation: literal ``\\n`` becomes a
    real newline, ``\\\\`` becomes ``\\``.
    """
    text = _trim_trailing(text or "")
    # Collapse double-backslashes
    prev = text
    while True:
        nxt = prev.replace("\\\\", "\\")
        if nxt == prev:
            break
        prev = nxt
    # Replace literal escape sequences
    prev = prev.replace("\\r", "\r")
    prev = prev.replace("\\n", "\n")
    prev = prev.replace("\\t", "\t")
    prev = prev.replace("\\b", "\x08")
    return _trim_trailing(prev)


def _get_label_value(labels: List[Dict[str, Any]], prefix: str) -> str:
    """Extract the value of the first label matching ``prefix``."""
    for lbl in labels:
        name = lbl.get("name", "")
        if name.startswith(prefix):
            return name[len(prefix):]
    return ""
