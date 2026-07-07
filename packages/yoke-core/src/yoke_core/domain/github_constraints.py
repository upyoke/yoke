"""GitHub REST constraints + sentinel predicates.

Single source of truth for limits and sentinel checks that previously
lived as scattered literals across the sync surfaces:

- :data:`MAX_LABEL_NAME_LEN` — GitHub rejects label names longer than 50
  characters. Long auto-generated ``worktree:<slug>`` labels (where the
  slug carries the parent epic id + a per-task suffix) silently broke
  every issue-create call by tripping HTTP 422 inside the labels payload.
- :func:`clamp_label_name` — preserves the category prefix (``worktree:``,
  ``status:``, etc.) and a leading slice of the value, replacing the
  excess with a short stable hash so two long slugs that share a prefix
  remain distinguishable.
- :func:`is_real_issue_num` — the dedup/create path returns ``"0"`` (or
  writes the sentinel ``#0`` into ``epic_tasks.github_issue``) when an
  issue could not be created. Lifecycle transitions, sync idempotency
  checks, and the "N created" counter must all treat that sentinel as
  unsynced so downstream code never tries to comment on ``#0``.
"""

from __future__ import annotations

import hashlib
from typing import Optional


MAX_LABEL_NAME_LEN = 50


def clamp_label_name(name: str) -> str:
    """Return ``name`` unchanged when it fits GitHub's label limit; otherwise
    truncate and append a short stable hash so collisions are unlikely.

    The hash suffix is derived from the full original name, so two distinct
    long names that share a prefix still produce distinct clamped names.
    """
    if len(name) <= MAX_LABEL_NAME_LEN:
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    # Reserve room for "-" + 8-char hash suffix (9 chars total).
    keep = MAX_LABEL_NAME_LEN - 9
    if keep < 1:
        # Degenerate case — return the hash alone.
        return digest
    return f"{name[:keep]}-{digest}"


def is_real_issue_num(value: Optional[str]) -> bool:
    """Return True when ``value`` is a non-sentinel GitHub issue number.

    Accepts both raw numeric strings ("123") and the "#"-prefixed shape
    stored in ``items.github_issue`` / ``epic_tasks.github_issue`` ("#123").
    The empty string, "null", "0", and "#0" all read as "not synced".
    """
    if value is None:
        return False
    stripped = str(value).strip().lstrip("#").strip()
    if not stripped or stripped == "null":
        return False
    try:
        return int(stripped) > 0
    except (TypeError, ValueError):
        return False
