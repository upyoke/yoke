"""REST coverage for the PR-merge ``Base branch was modified`` retry guard.

The retry-state-validation behavior the legacy subprocess wrapper
provided now lives in
:func:`yoke_core.engines.merge_worktree_pr_merge.run_pr_merge_with_retry_guard`.
The underlying transient-classification logic is covered in
:mod:`runtime.api.domain.test_gh_rest_transport`; these tests pin the
merge-engine wrapper's pre-retry validation behavior.
"""

from __future__ import annotations

from runtime.api.test_merge_worktree_pr_checks_test_helpers import _stub_ctx


def _stub_ctx_with_project(item_id, branch):
    ctx = _stub_ctx(item_id=item_id, branch=branch)
    ctx.project = "yoke"
    return ctx


def _make_merge_result(success, *, error_detail=None, retryable_signature=None):
    from yoke_core.engines.merge_worktree_pr_rest import PrMergeResult

    return PrMergeResult(
        success=success,
        error_detail=error_detail,
        retryable_signature=retryable_signature,
    )


def _make_state(status, mergeable):
    from yoke_core.engines.merge_worktree_pr_rest import PrMergeStateResult

    return PrMergeStateResult(merge_state_status=status, mergeable=mergeable)


class TestPrMergeRetryGuard:
    """``run_pr_merge_with_retry_guard`` retry-state-validation behaviour."""

    def test_base_branch_modified_retries_when_state_clean(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree_pr_merge
        from yoke_core.engines.merge_worktree_pr_merge import (
            run_pr_merge_with_retry_guard,
        )

        merge_results = [
            _make_merge_result(
                False,
                error_detail="merge rejected (HTTP 200): Base branch was modified",
                retryable_signature="graphql-base-branch-modified",
            ),
            _make_merge_result(True),
        ]
        monkeypatch.setattr(
            merge_worktree_pr_merge, "merge_pr", lambda *_a, **_kw: merge_results.pop(0)
        )
        monkeypatch.setattr(
            merge_worktree_pr_merge,
            "get_pr_merge_state",
            lambda *_a, **_kw: (_make_state("clean", "true"), None),
        )

        emitted: list[tuple[str, dict]] = []

        def _emit(name, **kw):
            emitted.append((name, kw))

        outcome = run_pr_merge_with_retry_guard(
            "3318",
            "https://example.com/pr/3318",
            _stub_ctx_with_project("1389", "YOK-1389"),
            _emit,
        )
        assert outcome.success
        assert any(n == "MergePullRequestMergeRetried" for n, _ in emitted)
        retried = next(kw for n, kw in emitted if n == "MergePullRequestMergeRetried")
        assert retried["context"]["pr_num"] == "3318"
        assert retried["context"]["merge_state_status"] == "clean"
        assert retried["context"]["mergeable"] == "true"

    def test_non_clean_pr_view_blocks_retry(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree_pr_merge
        from yoke_core.engines.merge_worktree_pr_merge import (
            run_pr_merge_with_retry_guard,
        )

        merge_results = [
            _make_merge_result(
                False,
                error_detail="merge rejected (HTTP 200): Base branch was modified",
                retryable_signature="graphql-base-branch-modified",
            ),
        ]
        monkeypatch.setattr(
            merge_worktree_pr_merge, "merge_pr", lambda *_a, **_kw: merge_results.pop(0)
        )
        monkeypatch.setattr(
            merge_worktree_pr_merge,
            "get_pr_merge_state",
            lambda *_a, **_kw: (_make_state("dirty", "false"), None),
        )

        emitted: list[tuple[str, dict]] = []
        outcome = run_pr_merge_with_retry_guard(
            "3318",
            "https://example.com/pr/3318",
            _stub_ctx_with_project("1389", "YOK-1389"),
            lambda name, **kw: emitted.append((name, kw)),
        )
        assert not outcome.success
        assert "refusing retry" in (outcome.error_detail or "")
        assert not any(n == "MergePullRequestMergeRetried" for n, _ in emitted)

    def test_non_signature_failures_do_not_retry(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree_pr_merge
        from yoke_core.engines.merge_worktree_pr_merge import (
            run_pr_merge_with_retry_guard,
        )

        calls = {"merge": 0}

        def _merge(*_a, **_kw):
            calls["merge"] += 1
            return _make_merge_result(
                False, error_detail="HTTP 409: conflict", retryable_signature=None
            )

        monkeypatch.setattr(merge_worktree_pr_merge, "merge_pr", _merge)
        outcome = run_pr_merge_with_retry_guard(
            "3318",
            "https://example.com/pr/3318",
            _stub_ctx_with_project("1389", "YOK-1389"),
            lambda *_a, **_kw: None,
        )
        assert not outcome.success
        assert calls["merge"] == 1  # not retried

    def test_persistent_base_branch_modified_terminal(self, monkeypatch) -> None:
        """Second merge attempt also fails — terminal failure surfaces truthfully."""
        from yoke_core.engines import merge_worktree_pr_merge
        from yoke_core.engines.merge_worktree_pr_merge import (
            run_pr_merge_with_retry_guard,
        )

        merge_results = [
            _make_merge_result(
                False,
                error_detail="merge rejected (HTTP 200): Base branch was modified",
                retryable_signature="graphql-base-branch-modified",
            ),
            _make_merge_result(
                False,
                error_detail="merge rejected (HTTP 200): Base branch was modified",
                retryable_signature="graphql-base-branch-modified",
            ),
        ]
        monkeypatch.setattr(
            merge_worktree_pr_merge, "merge_pr", lambda *_a, **_kw: merge_results.pop(0)
        )
        monkeypatch.setattr(
            merge_worktree_pr_merge,
            "get_pr_merge_state",
            lambda *_a, **_kw: (_make_state("clean", "true"), None),
        )

        outcome = run_pr_merge_with_retry_guard(
            "3318",
            "https://example.com/pr/3318",
            _stub_ctx_with_project("1389", "YOK-1389"),
            lambda *_a, **_kw: None,
        )
        assert not outcome.success
        assert "Base branch was modified" in (outcome.error_detail or "")
