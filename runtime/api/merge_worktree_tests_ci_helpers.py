"""Shared wiring for the merge boundary's CI-verification tests.

The gate's own cases and the candidate-input cases stub the same
boundaries — the lane's git and publish plumbing, the tree identity and
its CI head readback, the candidate the item's QA case declared, and the
evidence recorder. One copy here means a boundary that moves is
re-stubbed once.

The default wiring is a candidate whose QA case declares no producer
candidate, so every test that says nothing about one exercises the path
exactly as it did before that path had an alternative.
"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from yoke_core.domain import qa_case_ci_covering_run as covering_run
from yoke_core.domain.qa_case_ci_lane import WorkflowRun
from yoke_core.domain.verification_tree_binding import TreeIdentity
from yoke_core.engines import merge_worktree_tests_ci


def merge_ctx(tmp_path, *, project="yoke", item_id="42", local_verification=False):
    return SimpleNamespace(
        project=project,
        item_id=item_id,
        worktree_path=str(tmp_path),
        args=SimpleNamespace(
            branch="YOK-42",
            local_verification=local_verification,
        ),
    )


def stub_lane(
    monkeypatch, *, dispatch, await_result, covering=None, candidate=None,
):
    """Stub the boundaries the gate crosses; ``covering`` is the run it finds.

    ``None`` is an unexamined candidate, which is what every dispatch case
    below needs — the gate asks GitHub before it dispatches, and an
    unstubbed lookup would reach the network instead of answering.
    ``candidate`` is what the item's own QA case declares as the producer
    candidate the run must build against; ``None`` is the ordinary case
    that declares none.
    """
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_candidate_inputs.item_inputs",
        lambda **_kwargs: dict(candidate or {}),
    )
    monkeypatch.setattr(
        covering_run, "find_run_for_tree", lambda **_kwargs: covering,
    )
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "project_ci_workflow_file",
        lambda _p: "ci.yml",
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.repo_slug",
        lambda _c: "acme/widgets",
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.push_lane",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.github_actions_authority",
        lambda: nullcontext(),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.dispatch_workflow",
        dispatch,
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.await_workflow",
        await_result,
    )
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_parent",
        lambda: SimpleNamespace(_print=lambda *a, **k: None),
    )


def bind_candidate_tree(monkeypatch, tmp_path, head):
    """Bind the candidate tree and the CI head readback that must match it."""
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda _p: TreeIdentity(root=str(tmp_path), head_sha=head),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.run_head_sha", lambda **_k: head,
    )
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_tree_coverage._tree_object_id",
        lambda _cwd, _rev: "tree-identical",
    )


def run_verification(tmp_path, scope="full"):
    return merge_worktree_tests_ci.run_ci_verification(
        merge_ctx(tmp_path), scope=scope, command="python3 verify_tree.py",
    )


def existing_run(head, *, status="completed", conclusion="success", run_id="88"):
    return WorkflowRun(
        run_id, status, conclusion, f"https://github.test/runs/{run_id}", head,
    )


def record_ci_runs(monkeypatch):
    recorded: list[dict] = []
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_record_ci_run",
        lambda _ctx, **kwargs: recorded.append(kwargs) or 905,
    )
    return recorded


def never(reason):
    def _fail(**_kwargs):
        raise AssertionError(reason)

    return _fail


__all__ = [
    "bind_candidate_tree",
    "existing_run",
    "merge_ctx",
    "never",
    "record_ci_runs",
    "run_verification",
    "stub_lane",
]
