# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.merge_worktree_pr_checks_test_helpers_test_support import _stub_ctx

_PYTEST_PASS_OUTPUT = (
    "============================= test session starts ==============================\n"
    "collected 12 items\n\n"
    "tests/test_foo.py ............                                          [100%]\n\n"
    "============================== 12 passed in 1.42s =============================="
)

_PYTEST_FAILED_OUTPUT = (
    "============================= test session starts ==============================\n"
    "collected 12 items\n\n"
    "tests/test_foo.py ...F........                                          [100%]\n\n"
    "FAILED tests/test_foo.py::test_bar - AssertionError\n"
    "=========================== 1 failed, 11 passed ============================="
)

_HEAD_SHA = "abc1234def56789012345678901234567890abcd"

_OTHER_SHA = "9999999000000000000000000000000000000000"


def _stamp(output: str, sha: str) -> str:
    """Append the canonical head-SHA trailer to a captured verdict blob."""
    from yoke_core.domain.item_test_results_classify import (
        format_verdict_head_sha_trailer,
    )

    return output + "\n\n" + format_verdict_head_sha_trailer(sha)


def _event_names(emitted):
    return [name for (name, _kw) in emitted]


def _arm_pr_merge_environment(
    monkeypatch, *, ci_outcome, test_results: str, head_sha: str = _HEAD_SHA
):
    """Stub every helper upstream of the CI branch so the test sees only the
    gate's decision-making. Shared with ``test_merge_worktree_freshness``."""
    import subprocess
    from yoke_core.engines import merge_worktree
    from yoke_core.engines import merge_worktree_pr
    from yoke_core.engines import merge_worktree_pr_rest

    emitted: list[tuple[str, dict]] = []

    def _capture_event(event_name, **kw):
        emitted.append((event_name, kw))

    monkeypatch.setattr(merge_worktree, "_emit_merge_event", _capture_event)
    # These cases exercise the direct merge a project without a queue uses.
    monkeypatch.setattr(merge_worktree_pr, "queue_lane_landing", lambda _ctx: None)
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.push_lane", lambda *a, **k: None
    )
    monkeypatch.setattr(
        merge_worktree_pr, "_wait_for_ci", lambda *_a, **_kw: ci_outcome
    )
    # Freshness binding: the gate reads the PR head SHA to verify the local
    # verdict is bound to the merged commit.
    monkeypatch.setattr(
        merge_worktree_pr,
        "get_pr_head_sha",
        lambda *_a, **_kw: (head_sha, None),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "_read_item_test_results",
        lambda _item: test_results,
    )
    monkeypatch.setattr(
        merge_worktree,
        "_run_git",
        lambda *_a, **_kw: subprocess.CompletedProcess(
            [], 0, stdout="aaa\n", stderr=""
        ),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "create_pr",
        lambda *_a, **_kw: merge_worktree_pr_rest.PrCreateResult(
            pr_url="https://example/repo/pull/9999",
            pr_num="9999",
        ),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "find_existing_pr",
        lambda *_a, **_kw: (None, None),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "run_pr_merge_with_retry_guard",
        lambda *_a, **_kw: merge_worktree_pr_rest.PrMergeResult(success=True),
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "_post_merge_cleanup",
        lambda *_a, **_kw: 0,
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "_current_origin_target_sha",
        lambda *_a, **_kw: None,
    )
    return emitted
