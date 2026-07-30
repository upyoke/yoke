"""Data structures and normalization for resync detection.

Identity convention: inside the engine, backlog items are keyed by the
internal integer ``items.id`` (``item_id``) and epic tasks by
``(epic_id, task_num)``. The ``ref`` attribute is a human-facing label —
the item's public ref (``{public_item_prefix}-{project_sequence}``) for
backlog items — and is never parsed back into an id: public sequences
can diverge from internal ids, so a stripped label digit is not an
``items.id``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, NamedTuple, Optional

# GitHub issue titles written by the sync path lead with the item's
# public ref (e.g. ``[YOK-1914]``); the prefix letters vary per project.
ITEM_REF_TITLE_PREFIX_RE = re.compile(r"^\[[A-Za-z][A-Za-z0-9]*-\d+\]\s*")


class PairedItem:
    """Represents a local item/task paired with a GitHub issue."""

    __slots__ = (
        "ref", "file", "gh_num", "kind", "project", "repo",
        "item_id", "epic_id", "task_num",
    )

    def __init__(
        self,
        ref: str,
        file: str,
        gh_num: int,
        kind: str,
        project: str,
        repo: str,
        *,
        item_id: Optional[int] = None,
        epic_id: Optional[str] = None,
        task_num: Optional[int] = None,
    ):
        self.ref = ref
        self.file = file
        self.gh_num = gh_num
        self.kind = kind
        self.project = project
        self.repo = repo
        self.item_id = item_id
        self.epic_id = epic_id
        self.task_num = task_num


class DriftRecord:
    """A single field drift between local and GitHub.

    ``ref`` is the display label; the typed identity fields carry the
    authoritative key the repair stage acts on.
    """

    __slots__ = (
        "ref", "field", "local", "github",
        "item_id", "epic_id", "task_num",
    )

    def __init__(
        self,
        ref: str,
        field: str,
        local: str,
        github: str,
        *,
        item_id: Optional[int] = None,
        epic_id: Optional[str] = None,
        task_num: Optional[int] = None,
    ):
        self.ref = ref
        self.field = field
        self.local = local
        self.github = github
        self.item_id = item_id
        self.epic_id = epic_id
        self.task_num = task_num

    def to_pipe(self) -> str:
        return f"{self.ref}|{self.field}|{self.local}|{self.github}"


class LocalOrphan(NamedTuple):
    """A local backlog item or epic task with no linked GitHub issue."""

    ref: str
    file: str
    kind: str
    project: str
    item_id: Optional[int] = None
    epic_id: Optional[str] = None
    task_num: Optional[int] = None


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
