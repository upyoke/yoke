"""Merge-gate CI verification execution path unit tests."""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.verification_tree_binding import TreeIdentity
from yoke_core.engines import merge_worktree_tests_ci


def _ctx(tmp_path, *, project="yoke", item_id="42", local_verification=False):
    return SimpleNamespace(
        project=project,
        item_id=item_id,
        worktree_path=str(tmp_path),
        args=SimpleNamespace(
            branch="YOK-42",
            local_verification=local_verification,
        ),
    )


def _stub_lane(monkeypatch, *, dispatch, await_result):
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


def test_run_ci_verification_success_records_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    head = "b" * 40
    push_calls = []
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda _p: TreeIdentity(root=str(tmp_path), head_sha=head),
    )
    _stub_lane(
        monkeypatch,
        dispatch=lambda **kwargs: "55",
        await_result=lambda **kwargs: (0, "success"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.push_lane",
        lambda *a, **k: push_calls.append((a, k)),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.run_head_sha",
        lambda **kwargs: head,
    )
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_tree_coverage._tree_object_id",
        lambda _cwd, _rev: "tree-identical",
    )
    recorded = []
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_record_ci_run",
        lambda ctx, **kwargs: recorded.append(kwargs) or 901,
    )
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_parent",
        lambda: SimpleNamespace(_print=print),
    )

    result = merge_worktree_tests_ci.run_ci_verification(
        _ctx(tmp_path),
        scope="full",
        command="python3 verify_tree.py",
    )
    assert result is None
    assert push_calls, "candidate must be pushed before dispatch"
    assert recorded and recorded[0]["verdict"] == "pass"
    payload = json.loads(recorded[0]["raw_result"])
    assert payload["verification_tree"]["head_sha"] == head
    assert "actions/runs/55" in capsys.readouterr().out


def test_run_ci_verification_red_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    head = "c" * 40
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda _p: TreeIdentity(root=str(tmp_path), head_sha=head),
    )
    _stub_lane(
        monkeypatch,
        dispatch=lambda **kwargs: "66",
        await_result=lambda **kwargs: (1, "failed:failure"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.run_head_sha",
        lambda **kwargs: head,
    )
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_tree_coverage._tree_object_id",
        lambda _cwd, _rev: "tree-identical",
    )
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_record_ci_run",
        lambda *a, **k: 902,
    )
    assert merge_worktree_tests_ci.run_ci_verification(
        _ctx(tmp_path),
        scope="quick",
        command="python3 verify_tree.py",
    ) == (1, "tests failed")


def test_run_ci_verification_unreachable_named_failure_no_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    head = "d" * 40
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda _p: TreeIdentity(root=str(tmp_path), head_sha=head),
    )

    def boom(**kwargs):
        raise QaCaseExecutionError("dispatch unavailable")

    _stub_lane(
        monkeypatch,
        dispatch=boom,
        await_result=lambda **kwargs: (0, "success"),
    )
    recorded = []
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_record_ci_run",
        lambda *a, **k: recorded.append(k) or 903,
    )
    assert merge_worktree_tests_ci.run_ci_verification(
        _ctx(tmp_path),
        scope="full",
        command="python3 verify_tree.py",
    ) == (1, "ci unreachable")
    assert recorded and recorded[0]["verdict"] == "error"


def test_run_ci_verification_head_sha_mismatch_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    head = "e" * 40
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda _p: TreeIdentity(root=str(tmp_path), head_sha=head),
    )
    _stub_lane(
        monkeypatch,
        dispatch=lambda **kwargs: "77",
        await_result=lambda **kwargs: (0, "success"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.run_head_sha",
        lambda **kwargs: "f" * 40,
    )
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_tree_coverage._tree_object_id",
        lambda _cwd, rev: "tree-a" if rev == "HEAD" else "tree-b",
    )
    monkeypatch.setattr(
        merge_worktree_tests_ci,
        "_record_ci_run",
        lambda *a, **k: 904,
    )
    assert merge_worktree_tests_ci.run_ci_verification(
        _ctx(tmp_path),
        scope="full",
        command="python3 verify_tree.py",
    ) == (1, "ci unreachable")
