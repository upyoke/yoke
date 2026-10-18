"""Canonical Yoke git-hook coordination tokens.

The marker constants identify shims that ``yoke project install`` writes into
a project's ``.git/hooks/``. ``HEAD_RECORDING_GIT_HOOKS`` names the hooks
that record a checkout's HEAD as its lane head: every git operation that
moves HEAD fires at least one of them. The environment token lets a gate
that owns the final committed-tree binding suppress that recording during
replay.

These live in yoke-contracts so yoke-cli and yoke-core can share the same
identity without making yoke-core import yoke-cli.
"""

from __future__ import annotations

PRE_COMMIT_MARKER = "yoke-pre-commit"
POST_COMMIT_MARKER = "yoke-post-commit"
PRE_MERGE_COMMIT_MARKER = "yoke-pre-merge-commit"
POST_MERGE_MARKER = "yoke-post-merge"
POST_REWRITE_MARKER = "yoke-post-rewrite"
POST_CHECKOUT_MARKER = "yoke-post-checkout"
HEAD_RECORDING_GIT_HOOKS = (
    "post-commit",
    "post-merge",
    "post-rewrite",
    "post-checkout",
)
HEAD_RECORDING_SKIP_ENV = "YOKE_SKIP_HOOK_HEAD_RECORDING"

__all__ = [
    "HEAD_RECORDING_GIT_HOOKS",
    "HEAD_RECORDING_SKIP_ENV",
    "POST_CHECKOUT_MARKER",
    "POST_COMMIT_MARKER",
    "POST_MERGE_MARKER",
    "POST_REWRITE_MARKER",
    "PRE_COMMIT_MARKER",
    "PRE_MERGE_COMMIT_MARKER",
]
