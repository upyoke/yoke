"""Merge-worktree execution phase facade."""

from __future__ import annotations

from yoke_core.engines.merge_worktree_conflicts import (  # noqa: F401
    classify_conflict,
    is_additive_conflict,
    resolve_conflict,
    _resolve_additive_conflict,
    auto_resolve_conflicts,
    trial_merge,
)
from yoke_core.engines.merge_worktree_rebase import do_rebase_or_merge  # noqa: F401
from yoke_core.engines.merge_worktree_tests import (  # noqa: F401
    _terminate_process_tree,
    _run_streaming,
    run_tests as _run_project_tests,
)


def run_tests(ctx):
    result = _run_project_tests(ctx)
    if result:
        return result
    from yoke_core.engines.merge_worktree_consumer_proof import require_consumer_proof

    refusal = require_consumer_proof(ctx)
    if refusal:
        from yoke_core.engines import merge_worktree

        merge_worktree._print(refusal, err=True)
        return 1, refusal
    return None
