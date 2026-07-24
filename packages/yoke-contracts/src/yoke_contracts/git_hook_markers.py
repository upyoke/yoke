"""Canonical Yoke git-hook marker strings.

These three constants identify the Yoke-managed git-hook shims that
``yoke project install`` writes into a project's ``.git/hooks/``. Each shim
carries its marker in a leading comment line, so a marker's presence in a
hook file is the recognition signal for "this is the Yoke shim".

They live in yoke-contracts so that both yoke-cli (which authors the shims)
and yoke-core (whose doctor gate-liveness check recognizes an installed
shim on disk) can import the same strings. yoke-core must not import
yoke-cli, so the shared identity has to sit in the package both depend on.
"""

from __future__ import annotations

PRE_COMMIT_MARKER = "yoke-pre-commit"
POST_COMMIT_MARKER = "yoke-post-commit"
PRE_MERGE_COMMIT_MARKER = "yoke-pre-merge-commit"

__all__ = [
    "PRE_COMMIT_MARKER",
    "POST_COMMIT_MARKER",
    "PRE_MERGE_COMMIT_MARKER",
]
