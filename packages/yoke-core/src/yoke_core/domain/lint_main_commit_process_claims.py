"""Helpers for ``lint_main_commit`` that consume process/path-claim state.

``is_actual_git_commit`` now lives in
``yoke_contracts.hook_runner.main_commit`` so the product client and
authority policy share one shell classifier. This module keeps the
compatibility import and owns the authority-backed strategy authorization:

* :func:`is_strategy_commit_authorized` — the matches-the-master rule:
  return ``True`` when every staged non-bookkeeping file is a canonical
  strategy rendered view whose STAGED content byte-matches its live
  ``strategy_docs`` DB row (header parses, ``updated_at`` current, body
  hash equals the row content). Fresh renders are always safe to commit
  on ``main`` — this authorizes strategize/feed render commits and
  operator post-ingest commits alike, with no claim lookup at commit
  time.

The authoritative rows resolve through the shared dispatcher-backed
loader (:func:`lint_main_commit_strategy_freshness.load_project_strategy_rows`),
which rides the active transport — in-process under local-postgres, the
https relay otherwise. The helpers fail closed: an unmapped checkout, a
dispatcher refusal, a transport failure, or an unparseable header
returns ``False`` so the lint falls through to its existing
infrastructure-failure short-circuit (``_active_worktree_items``
returning ``None``) — never an implicit allow.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from yoke_contracts.hook_runner.main_commit import is_actual_git_commit


# ---------------------------------------------------------------------------
# Matches-the-master authorization for strategy rendered-view commits
# ---------------------------------------------------------------------------


def _staged_blob(path: str) -> Optional[str]:
    """Return the STAGED content of *path* (``git show :<path>``).

    The commit ships the index, not the working tree — authorizing on
    the worktree file would let a stale staged copy ride a fresh-looking
    file (and vice versa deny a fresh staged copy under a dirty file).
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "show", f":{path}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _commit_repo_project_context() -> Optional[str]:
    """Client project context for the checkout issuing the commit.

    The lint evaluates inside whatever checkout issued ``git commit``
    (the hook chain is installed in every Yoke-managed repo) and uses
    the strategy CLI adapters' own resolution chain
    (:func:`yoke_cli.commands._helpers.client_project_context`:
    ``$YOKE_PROJECT``, then the machine-config checkout→project map
    for the cwd's repo root) so the lint and ``yoke strategy ...``
    always agree on which project's corpus governs this checkout.
    ``None`` (unmapped checkout, no config) fails the protections
    closed.
    """
    try:
        from yoke_cli.commands._helpers import (
            client_project_context,
        )

        return client_project_context(None)
    except Exception:
        return None


def is_strategy_commit_authorized(
    staged_non_bookkeeping: Sequence[str],
    *,
    worktree_content_paths: frozenset = frozenset(),
    rows_cache: Optional[dict] = None,
    project_ctx: Optional[str] = None,
    client_strategy_blobs: Optional[Mapping[str, Mapping[str, object]]] = None,
) -> bool:
    """Return ``True`` iff every staged file is a fresh strategy render.

    The matches-the-master rule for the tracked ``.yoke/strategy/``
    rendered views: a strategy commit on main is authorized exactly when
    each staged file byte-matches the live ``strategy_docs`` row of the
    project this checkout maps to — its YOKE:STRATEGY-DOC header
    parses, names the right slug, carries the row's current
    ``updated_at``, and the staged body hashes to the row's content. You
    can only commit what the master already says, so no claim check is
    needed at commit time (the process claim keeps serializing
    strategize/feed sessions and gating the replace path).

    ``worktree_content_paths`` members (same-command ``git add`` targets)
    verify the WORKTREE file instead of the index blob:
    the pending add overwrites the index entry, so that is the content the
    commit ships.

    Holds only when ALL staged non-bookkeeping files are strategy
    rendered views; mixed commits fall through to the normal item-claim
    rules. The rows resolve through the shared dispatcher-backed loader
    (one ``strategy.render.run`` over the active transport;
    ``rows_cache`` shares the fetch with the freshness deny that ran in
    the same evaluation). An unmapped checkout or any loader failure
    authorizes nothing — fail closed.
    """
    if not staged_non_bookkeeping:
        return False
    from yoke_core.domain.strategy_docs_paths import slug_from_view_path

    staged = list(staged_non_bookkeeping)
    slugs_by_path = {path: slug_from_view_path(path) for path in staged}
    if not all(slugs_by_path.values()):
        return False
    resolved_project = project_ctx or _commit_repo_project_context()
    if resolved_project is None:
        return False

    try:
        from yoke_core.domain.lint_main_commit_client_blobs import (
            client_blob_freshness_finding,
        )
        from yoke_core.domain.lint_main_commit_strategy_freshness import (
            load_project_strategy_rows,
        )
        from yoke_core.domain.strategy_docs_header import (
            StrategyHeaderError,
            content_sha256,
            parse_file_text,
        )
    except Exception:
        return False

    rows, _failure = load_project_strategy_rows(
        resolved_project, slugs_by_path.values(), rows_cache=rows_cache,
    )
    if rows is None:
        return False

    for path in staged:
        slug = slugs_by_path[path]
        if client_strategy_blobs is not None:
            if client_blob_freshness_finding(
                rows, slug, client_strategy_blobs.get(path),
            ) is not None:
                return False
            continue
        row = rows.get(slug)
        if path in worktree_content_paths:
            from yoke_core.domain.lint_staged_union import worktree_blob

            blob = worktree_blob(path)
        else:
            blob = _staged_blob(path)
        if row is None or blob is None or slug is None:
            return False
        try:
            header = parse_file_text(blob)
        except StrategyHeaderError:
            return False
        db_updated_at, db_content = row
        if header.slug != slug or header.updated_at != db_updated_at:
            return False
        if content_sha256(header.body) != content_sha256(db_content):
            return False
    return True


__all__ = [
    "is_actual_git_commit",
    "is_strategy_commit_authorized",
]
