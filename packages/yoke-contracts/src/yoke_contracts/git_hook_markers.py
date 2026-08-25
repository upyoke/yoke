"""Canonical Yoke git-hook coordination tokens.

The marker constants identify shims that ``yoke project install`` writes into
a project's ``.git/hooks/``. The environment token lets a gate that owns the
final committed-tree binding suppress redundant snapshot sync during replay.

These live in yoke-contracts so yoke-cli and yoke-core can share the same
identity without making yoke-core import yoke-cli.
"""

from __future__ import annotations

PRE_COMMIT_MARKER = "yoke-pre-commit"
POST_COMMIT_MARKER = "yoke-post-commit"
PRE_MERGE_COMMIT_MARKER = "yoke-pre-merge-commit"
POST_COMMIT_SNAPSHOT_SKIP_ENV = "YOKE_SKIP_POST_COMMIT_SNAPSHOT_SYNC"

__all__ = [
    "PRE_COMMIT_MARKER",
    "POST_COMMIT_MARKER",
    "POST_COMMIT_SNAPSHOT_SKIP_ENV",
    "PRE_MERGE_COMMIT_MARKER",
]
