"""Post-rebase merge verification through materialized QA plan cases."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import qa_case_execution
from yoke_core.engines import merge_worktree_tests


def _ctx(tmp_path, *, project="example", item_id="42"):
    return SimpleNamespace(
        project=project,
        item_id=item_id,
        worktree_path=str(tmp_path),
    )


def test_run_tests_executes_materialized_post_rebase_case(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_post_rebase_requirement_id",
        lambda _ctx: 73,
    )
    seen = []

    def execute(requirement_id, **kwargs):
        seen.append((requirement_id, kwargs))
        return {
            "requirement_id": requirement_id,
            "run_id": 88,
            "artifact_id": 91,
            "verdict": "pass",
        }

    monkeypatch.setattr(qa_case_execution, "execute_case", execute)
    assert merge_worktree_tests.run_tests(_ctx(tmp_path)) is None
    assert seen == [(73, {"checkout_path": str(tmp_path)})]
    output = capsys.readouterr().out
    assert "post-rebase QA plan case (requirement 73)" in output
    assert "QA run 88 artifact 91 verdict pass" in output


def test_run_tests_blocks_when_post_rebase_case_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_post_rebase_requirement_id",
        lambda _ctx: 73,
    )
    monkeypatch.setattr(
        qa_case_execution,
        "execute_case",
        lambda _requirement_id, **_kwargs: {
            "run_id": 88,
            "artifact_id": 91,
            "verdict": "fail",
        },
    )
    assert merge_worktree_tests.run_tests(_ctx(tmp_path)) == (
        1, "tests failed",
    )


def test_run_tests_skips_registered_project_without_post_rebase_plan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_post_rebase_requirement_id",
        lambda _ctx: None,
    )
    assert merge_worktree_tests.run_tests(_ctx(tmp_path)) is None
    assert (
        "no post-rebase QA plan attached for project 'example'"
        in capsys.readouterr().out
    )
